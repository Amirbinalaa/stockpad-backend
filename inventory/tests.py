from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Material, StockTransaction, EngineerConnection



User = get_user_model()


class InventoryTests(TestCase):
    """
    Tests for materials, stock transactions, dashboard, and reports.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="invuser", password="pass123456", role="admin"
        )
        login_resp = self.client.post(
            "/api/auth/login/",
            {"username": "invuser", "password": "pass123456"},
            format="json",
        )
        self.access = login_resp.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")

    def test_create_material_with_initial_quantity(self):
        """Create material, set current_quantity, and create initial IN transaction."""
        url = reverse("inventory:material-list-create")
        payload = {
            "name": "Cement",
            "unit": "kg",
            "initial_quantity": "100.5",
            "low_stock_threshold_percent": 20,
        }
        resp = self.client.post(url, payload, format="json")

        self.assertEqual(resp.status_code, 201)
        mat = Material.objects.get(name="Cement")
        self.assertEqual(mat.current_quantity, Decimal("100.50"))
        self.assertTrue(
            StockTransaction.objects.filter(
                material=mat,
                type=StockTransaction.TYPE_IN,
                quantity=Decimal("100.50"),
            ).exists()
        )

    def test_create_material_requires_auth(self):
        """Anonymous user cannot create materials."""
        anon = APIClient()
        url = reverse("inventory:material-list-create")
        resp = anon.post(
            url,
            {
                "name": "Steel",
                "unit": "kg",
                "initial_quantity": "10",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 401)

    def _create_material(self):
        """Helper to create a material for transaction tests."""
        mat = Material.objects.create(
            user=self.user,
            name="Cement",
            unit="kg",
            current_quantity=Decimal("50.00"),
            low_stock_threshold_percent=20,
        )
        return mat

    def test_stock_increases_on_in_transaction(self):
        """IN transaction increases material.current_quantity."""
        mat = self._create_material()
        url = reverse("inventory:transaction-list-create")
        payload = {
            "material": mat.id,
            "type": "in",
            "quantity": "25.5",
            "notes": "Supplier X",
        }
        resp = self.client.post(url, payload, format="json")
        self.assertEqual(resp.status_code, 201)

        mat.refresh_from_db()
        self.assertEqual(mat.current_quantity, Decimal("75.50"))

    def test_stock_decreases_on_out_transaction(self):
        """OUT transaction decreases material.current_quantity and creates a row."""
        mat = self._create_material()
        url = reverse("inventory:transaction-list-create")
        payload = {
            "material": mat.id,
            "type": "out",
            "quantity": "20.0",
            "notes": "Usage",
        }
        resp = self.client.post(url, payload, format="json")
        self.assertEqual(resp.status_code, 201)

        mat.refresh_from_db()
        self.assertEqual(mat.current_quantity, Decimal("30.00"))
        self.assertTrue(
            StockTransaction.objects.filter(
                material=mat, type="out", quantity=Decimal("20.0")
            ).exists()
        )

    def test_out_transaction_cannot_go_negative(self):
        """Reject OUT transaction that would make stock negative."""
        mat = self._create_material()
        url = reverse("inventory:transaction-list-create")
        payload = {
            "material": mat.id,
            "type": "out",
            "quantity": "1000.0",
            "notes": "Bad",
        }
        resp = self.client.post(url, payload, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("quantity", resp.data)

        mat.refresh_from_db()
        self.assertEqual(mat.current_quantity, Decimal("50.00"))

    def test_dashboard_low_stock_flag(self):
        """Dashboard marks items as low stock based on threshold percent."""
        Material.objects.create(
            user=self.user,
            name="LowItem",
            unit="kg",
            current_quantity=Decimal("10.0"),
            low_stock_threshold_percent=20,
        )
        Material.objects.create(
            user=self.user,
            name="OkItem",
            unit="kg",
            current_quantity=Decimal("80.0"),
            low_stock_threshold_percent=20,
        )

        resp = self.client.get(reverse("inventory:dashboard-summary"))
        self.assertEqual(resp.status_code, 200)
        data = {item["name"]: item for item in resp.data}
        self.assertTrue(data["LowItem"]["is_low_stock"])
        self.assertFalse(data["OkItem"]["is_low_stock"])

    def test_reports_filter_and_summary(self):
        """Reports endpoint filters and aggregates in/out/net correctly."""
        mat1 = Material.objects.create(
            user=self.user,
            name="Item1", unit="kg", current_quantity=Decimal("0.0")
        )

        StockTransaction.objects.create(
            material=mat1,
            type="in",
            quantity=Decimal("10.0"),
            performed_by=self.user,
        )
        StockTransaction.objects.create(
            material=mat1,
            type="out",
            quantity=Decimal("4.0"),
            performed_by=self.user,
        )

        url = reverse("inventory:reports")
        resp = self.client.get(
            url,
            {
                "material": mat1.id,
                "type": "both",
                "period": "all",
            },
        )
        self.assertEqual(resp.status_code, 200)
        summary = resp.data["summary"]
        self.assertEqual(Decimal(str(summary["total_in"])), Decimal("10.0"))
        self.assertEqual(Decimal(str(summary["total_out"])), Decimal("4.0"))
        self.assertEqual(Decimal(str(summary["net"])), Decimal("6.0"))
        self.assertEqual(summary["count"], 2)


from unittest.mock import patch
from .models import MaterialRequest

class MaterialRequestWebhookTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.superuser = User.objects.create_superuser(
            username="adminuser", password="adminpass123", email="admin@example.com"
        )
        self.user = User.objects.create_user(
            username="testuser", password="userpass123", email="user@example.com"
        )
        self.material = Material.objects.create(
            user=self.user,
            name="Sand",
            unit="kg",
            current_quantity=Decimal("100.0"),
        )
        # Auth header for Site B calls
        self.headers = {
            "HTTP_X_SITE_B_API_KEY": "Ya3OF1R5KD7xO4INNwFOgYWfb8NCpJVbxMB6hif_1Hg"
        }
        # Pre-authorise the engineers used in the tests below
        from .models import EngineerConnection
        EngineerConnection.objects.create(
            manager=self.user,
            engineer_email="user@example.com",
            is_active=True,
        )
        EngineerConnection.objects.create(
            manager=self.superuser,
            engineer_email="unknown@example.com",
            is_active=True,
        )

    @patch("inventory.tasks.ping_site_b_health", return_value=True)
    @patch("requests.post")
    def test_create_material_request_success_and_webhook(self, mock_post, mock_health):
        """Site B can create request using API key. Webhook is sent. Fallback user assigned."""
        url = reverse("inventory:request-create")
        payload = {
            "material": self.material.id,
            "requester_id": "eng-123",
            "requester_email": "user@example.com",
            "quantity": "25.0",
            "reason": "Need sand",
            "webhook_url": "https://site-b.com/webhooks/requests/",
        }
        
        # Call API
        resp = self.client.post(url, payload, format="json", **self.headers)
        self.assertEqual(resp.status_code, 201)
        
        # Verify db request created
        req = MaterialRequest.objects.get(id=resp.data["id"])
        self.assertEqual(req.status, "pending")
        self.assertEqual(req.quantity, Decimal("25.0"))
        
        # Verify material owner fallback user set (user@example.com found in db)
        self.material.refresh_from_db()
        self.assertEqual(self.material.user, self.user)
        
        # Verify webhook was POSTed with HMAC-signed headers
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        self.assertEqual(call_kwargs[0][0], "https://site-b.com/webhooks/requests/")
        self.assertIn("X-Site-A-Signature", call_kwargs[1]["headers"])

    @patch("inventory.tasks.ping_site_b_health", return_value=True)
    @patch("requests.post")
    def test_create_material_request_fallback_superuser(self, mock_post, mock_health):
        """If requester_email is not found, fallback to superuser (admin)."""
        # Clear owner of material for test
        self.material.user = None
        self.material.save()

        url = reverse("inventory:request-create")
        payload = {
            "material": self.material.id,
            "requester_id": "eng-124",
            "requester_email": "unknown@example.com",
            "quantity": "10.0",
            "reason": "Build",
            "webhook_url": "https://site-b.com/webhooks/requests/",
        }
        
        resp = self.client.post(url, payload, format="json", **self.headers)
        self.assertEqual(resp.status_code, 201)
        
        # Verify material owner set to first superuser
        self.material.refresh_from_db()
        self.assertEqual(self.material.user, self.superuser)

    @patch("inventory.tasks.ping_site_b_health", return_value=True)
    @patch("requests.post")
    def test_review_material_request_webhook(self, mock_post, mock_health):
        """Approving request triggers second webhook with approved status."""
        req = MaterialRequest.objects.create(
            material=self.material,
            requester_id="eng-123",
            requester_email="user@example.com",
            quantity=Decimal("20.0"),
            webhook_url="https://site-b.com/webhooks/requests/",
            status="pending"
        )
        # Login manager
        login_resp = self.client.post(
            "/api/auth/login/",
            {"username": "testuser", "password": "userpass123"},
            format="json",
        )
        access = login_resp.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        
        # Approve request
        url = reverse("inventory:request-review", kwargs={"pk": req.id})
        payload = {
            "status": "approved",
            "review_notes": "All set"
        }
        resp = self.client.patch(url, payload, format="json")
        self.assertEqual(resp.status_code, 200)
        
        # Verify db
        req.refresh_from_db()
        self.assertEqual(req.status, "approved")
        
        # Verify webhook POSTed with HMAC-signed headers
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        self.assertEqual(call_kwargs[0][0], "https://site-b.com/webhooks/requests/")
        self.assertIn("X-Site-A-Signature", call_kwargs[1]["headers"])

    @patch("inventory.tasks.ping_site_b_health", return_value=False)
    def test_webhook_retry_exhaustion_creates_dead_letter_log(self, mock_health):
        """When health check fails on all attempts, task exhausts retries and creates a WebhookDeliveryLog record."""
        from .models import WebhookDeliveryLog
        from .tasks import send_webhook_task

        webhook_url = "https://site-b.com/webhooks/dead-letter-test/"
        payload = {
            "id": 999,
            "status": "pending",
            "event_id": "11111111-2222-3333-4444-555555555555",
        }

        # Call apply with retries at max_retries to trigger MaxRetriesExceeded handling
        try:
            send_webhook_task.apply(args=[webhook_url, payload], retries=3)
        except Exception:
            pass

        # Assert WebhookDeliveryLog was created with correct fields
        log = WebhookDeliveryLog.objects.filter(webhook_url=webhook_url).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.webhook_url, webhook_url)
        self.assertEqual(str(log.event_id), "11111111-2222-3333-4444-555555555555")
        self.assertEqual(log.attempt_count, 3)
        self.assertEqual(log.status, WebhookDeliveryLog.STATUS_FAILED)
        self.assertIn("Site B health check failed", log.error_message)




class TeamAccessControlTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.manager = User.objects.create_user(
            username="manager1", password="password123", email="manager1@example.com"
        )
        # Login manager
        login_resp = self.client.post(
            "/api/auth/login/",
            {"username": "manager1", "password": "password123"},
            format="json",
        )
        self.access = login_resp.data["access"]
        
        self.material = Material.objects.create(
            user=self.manager,
            name="Cement",
            unit="kg",
            current_quantity=Decimal("50.0")
        )
        # Auth header for Site B calls
        self.site_b_headers = {
            "HTTP_X_SITE_B_API_KEY": "Ya3OF1R5KD7xO4INNwFOgYWfb8NCpJVbxMB6hif_1Hg"
        }

    def test_connections_api_crud(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        url = reverse("inventory:connections-list")
        
        # 1. GET list (initially empty)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 0)
        
        # 2. POST create connection
        payload = {"engineer_email": "engineer1@example.com"}
        resp = self.client.post(url, payload, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["engineer_email"], "engineer1@example.com")
        self.assertTrue(resp.data["is_active"])
        
        # 3. GET list (now contains 1 connection)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["engineer_email"], "engineer1@example.com")
        
        # 4. POST duplicate connection (should fail)
        resp = self.client.post(url, payload, format="json")
        self.assertEqual(resp.status_code, 400)
        
        # 5. DELETE connection
        list_resp = self.client.get(url)
        conn_id = list_resp.data[0]["id"]
        
        detail_url = reverse("inventory:connections-detail", kwargs={"pk": conn_id})
        resp = self.client.delete(detail_url)
        self.assertEqual(resp.status_code, 200)
        
        # 6. GET list (should be empty again because it's inactive)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 0)
        
        # 7. POST reactivate connection (should succeed)
        resp = self.client.post(url, payload, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["engineer_email"], "engineer1@example.com")
        self.assertTrue(resp.data["is_active"])

    @patch("inventory.tasks.ping_site_b_health", return_value=True)
    @patch("requests.post")
    def test_request_creation_security_enforcement(self, mock_post, mock_health):
        # 1. Attempt request submission without active connection (fails with 403)
        url = reverse("inventory:request-create")
        payload = {
            "material": self.material.id,
            "requester_id": "eng-999",
            "requester_email": "untrusted@example.com",
            "quantity": "10.0",
            "reason": "Building foundation",
            "webhook_url": "https://site-b.com/webhooks/",
        }
        
        resp = self.client.post(url, payload, format="json", **self.site_b_headers)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["error"], "Unauthorized. This engineer's email is not connected to the warehouse manager.")
        
        # 2. Add connection for the email
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        conn_url = reverse("inventory:connections-list")
        self.client.post(conn_url, {"engineer_email": "untrusted@example.com"}, format="json")
        
        # 3. Attempt request submission again (succeeds with 201)
        # Clear client auth credentials so we rely purely on X-Site-B-API-Key header
        self.client.credentials()
        resp = self.client.post(url, payload, format="json", **self.site_b_headers)
        self.assertEqual(resp.status_code, 201)



class EngineerPEApiTests(TestCase):
    """Site B catalog + connection check endpoints for PE clients."""

    def setUp(self):
        self.client = APIClient()
        self.manager = User.objects.create_user(
            username="wmgr",
            password="pass123456",
            email="manager@example.com",
            role="admin",
        )
        self.other_manager = User.objects.create_user(
            username="othermgr",
            password="pass123456",
            email="other@example.com",
            role="admin",
        )
        self.material = Material.objects.create(
            user=self.manager,
            name="Cement",
            unit="kg",
            current_quantity=Decimal("150.00"),
            max_quantity=Decimal("500.00"),
            low_stock_threshold_percent=20,
        )
        Material.objects.create(
            user=self.other_manager,
            name="Hidden Steel",
            unit="kg",
            current_quantity=Decimal("999.00"),
        )
        EngineerConnection.objects.create(
            manager=self.manager,
            engineer_email="engineer@example.com",
            is_active=True,
        )
        self.headers = {
            "HTTP_X_SITE_B_API_KEY": "Ya3OF1R5KD7xO4INNwFOgYWfb8NCpJVbxMB6hif_1Hg"
        }

    def test_engineer_connection_check_active(self):
        url = reverse("inventory:connections-check")
        resp = self.client.get(url, {"email": "engineer@example.com"}, **self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["connected"])
        self.assertTrue(resp.data["is_active"])
        self.assertIsNotNone(resp.data["engineer_id"])
        self.assertEqual(resp.data["engineer_email"], "engineer@example.com")

    def test_engineer_connection_check_not_connected(self):
        url = reverse("inventory:engineers-status")
        resp = self.client.get(url, {"email": "unknown@example.com"}, **self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["connected"])
        self.assertFalse(resp.data["is_active"])
        self.assertIsNone(resp.data["engineer_id"])

    def test_engineer_catalog_quantity_and_category_fields(self):
        url = reverse("inventory:engineer-catalog")
        resp = self.client.get(
            url, {"email": "engineer@example.com"}, **self.headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        item = resp.data[0]
        self.assertEqual(item["name"], "Cement")
        self.assertEqual(item["quantity"], 150.0)
        self.assertEqual(item["quantity_available"], 150.0)
        self.assertEqual(item["current_quantity"], 150.0)
        self.assertEqual(item["stock_status"], "in_stock")
        self.assertEqual(item["category_name"], "Raw Materials")
        self.assertEqual(item["category"]["name"], "Raw Materials")

    def test_engineer_catalog_scoped_to_manager(self):
        url = reverse("inventory:material-catalog")
        resp = self.client.get(
            url, {"email": "engineer@example.com"}, **self.headers
        )
        self.assertEqual(resp.status_code, 200)
        names = [item["name"] for item in resp.data]
        self.assertIn("Cement", names)
        self.assertNotIn("Hidden Steel", names)

    def test_engineer_catalog_rejects_unconnected_email(self):
        url = reverse("inventory:material-catalog")
        resp = self.client.get(
            url, {"email": "stranger@example.com"}, **self.headers
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(resp.data["connected"])


from django.test import TestCase, override_settings


@override_settings(SITE_B_API_KEY="test_b2b_secret")
class Phase4CachingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="manager1",
            email="manager1@example.com",
            password="password123",
        )
        self.user2 = User.objects.create_user(
            username="manager2",
            email="manager2@example.com",
            password="password123",
        )
        self.material1 = Material.objects.create(
            user=self.user,
            name="Alpha Item",
            unit=Material.UNIT_KG,
            current_quantity=Decimal("100.00"),
            cost_price=Decimal("10.00"),
            is_active=True,
        )
        self.material2 = Material.objects.create(
            user=self.user2,
            name="Beta Item",
            unit=Material.UNIT_PCS,
            current_quantity=Decimal("50.00"),
            cost_price=Decimal("20.00"),
            is_active=True,
        )
        self.conn1 = EngineerConnection.objects.create(
            manager=self.user,
            engineer_email="engineer1@example.com",
            is_active=True,
        )
        self.conn2 = EngineerConnection.objects.create(
            manager=self.user2,
            engineer_email="engineer2@example.com",
            is_active=True,
        )
        self.api_key = "test_b2b_secret"
        self.client = APIClient()
        self.headers = {"HTTP_X_SITE_B_API_KEY": self.api_key}
        cache.clear()

    def test_ai_insights_caching_and_recompute_task(self):
        from inventory.tasks import recompute_ai_insights_task
        self.client.force_authenticate(user=self.user)
        url = reverse("inventory:insights")

        # First request computes and caches insights
        resp1 = self.client.get(url)
        self.assertEqual(resp1.status_code, 200)
        cache_key = f"ai_insights_user_{self.user.id}"
        cached_data = cache.get(cache_key)
        self.assertIsNotNone(cached_data)
        self.assertIn("metrics", cached_data)

        # Subsequent request retrieves from cache
        resp2 = self.client.get(url)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.data, cached_data)

        # Celery recompute task refreshes cache
        task_result = recompute_ai_insights_task(user_id=self.user.id)
        self.assertIn("Recomputed AI insights", task_result)
        refreshed_cache = cache.get(cache_key)
        self.assertIsNotNone(refreshed_cache)

    def test_material_catalog_caching_and_invalidation(self):
        url = reverse("inventory:material-catalog")
        
        # 1. Initial version and fetch populates cache under v1
        version_before = cache.get("catalog_cache_version", 1)
        resp1 = self.client.get(url, {"email": "engineer1@example.com"}, **self.headers)
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(len(resp1.data), 1)
        self.assertEqual(resp1.data[0]["name"], "Alpha Item")
        self.assertEqual(float(resp1.data[0]["quantity"]), 100.0)

        old_cache_key = f"catalog_payload_v{version_before}_engineer1@example.com"
        self.assertIsNotNone(cache.get(old_cache_key))

        # 2. Modifying stock level and saving material triggers catalog cache invalidation signal
        self.material1.current_quantity = Decimal("150.00")
        self.material1.save()
        StockTransaction.objects.create(
            material=self.material1,
            type=StockTransaction.TYPE_IN,
            quantity=Decimal("50.00"),
            performed_by=self.user,
        )
        self.material1.refresh_from_db()
        self.assertEqual(self.material1.current_quantity, Decimal("150.00"))

        version_after = cache.get("catalog_cache_version")
        self.assertGreater(version_after, version_before)

        # 3. Next fetch returns fresh updated stock quantity under new version key
        resp2 = self.client.get(url, {"email": "engineer1@example.com"}, **self.headers)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(float(resp2.data[0]["quantity"]), 150.0)

        new_cache_key = f"catalog_payload_v{version_after}_engineer1@example.com"
        self.assertIsNotNone(cache.get(new_cache_key))



    def test_catalog_cache_isolation_per_engineer(self):
        url = reverse("inventory:material-catalog")

        resp_eng1 = self.client.get(url, {"email": "engineer1@example.com"}, **self.headers)
        self.assertEqual(resp_eng1.status_code, 200)
        self.assertEqual(len(resp_eng1.data), 1)
        self.assertEqual(resp_eng1.data[0]["name"], "Alpha Item")

        resp_eng2 = self.client.get(url, {"email": "engineer2@example.com"}, **self.headers)
        self.assertEqual(resp_eng2.status_code, 200)
        self.assertEqual(len(resp_eng2.data), 1)
        self.assertEqual(resp_eng2.data[0]["name"], "Beta Item")


class Phase5AlertingAndRotationTests(TestCase):
    """
    Tests for Phase 5 — webhook retry spike alerting and key rotation.
    """

    def setUp(self):
        self.manager = User.objects.create_user(
            username="p5manager",
            email="p5manager@example.com",
            password="password123",
        )
        self.material = Material.objects.create(
            user=self.manager,
            name="Phase5 Steel",
            unit=Material.UNIT_KG,
            current_quantity=Decimal("100.00"),
            is_active=True,
        )
        EngineerConnection.objects.create(
            manager=self.manager,
            engineer_email="p5eng@example.com",
            is_active=True,
        )
        self.client = APIClient()
        cache.clear()

    # ── Spike alerting ────────────────────────────────────────────────────────

    @override_settings(WEBHOOK_RETRY_SPIKE_THRESHOLD=3)
    def test_retry_counter_increments_and_alert_fires(self):
        """
        _increment_retry_counter() increments the rolling counter;
        once the counter reaches the threshold _emit_spike_alert produces
        a CRITICAL log and check_webhook_retry_spike returns the SPIKE message.
        """
        from inventory.tasks import (
            _increment_retry_counter,
            _RETRY_SPIKE_COUNTER_KEY,
            check_webhook_retry_spike,
        )

        # Counter starts at zero
        self.assertEqual(cache.get(_RETRY_SPIKE_COUNTER_KEY, 0), 0)

        # Increment three times — should reach threshold
        _increment_retry_counter()
        _increment_retry_counter()
        v = _increment_retry_counter()
        self.assertEqual(v, 3)
        self.assertEqual(cache.get(_RETRY_SPIKE_COUNTER_KEY), 3)

        # Periodic check task should detect the spike
        with self.assertLogs("inventory.tasks", level="CRITICAL") as cm:
            result = check_webhook_retry_spike()

        self.assertIn("SPIKE ALERT FIRED", result)
        self.assertTrue(any("[WM ALERT]" in line for line in cm.output))

    @override_settings(WEBHOOK_RETRY_SPIKE_THRESHOLD=10)
    def test_check_spike_task_returns_ok_when_below_threshold(self):
        """
        check_webhook_retry_spike returns an OK string when below threshold.
        """
        from inventory.tasks import check_webhook_retry_spike, _increment_retry_counter
        _increment_retry_counter()  # only 1 retry, threshold is 10
        result = check_webhook_retry_spike()
        self.assertTrue(result.startswith("OK"))

    # ── Dual-key rotation ─────────────────────────────────────────────────────

    @override_settings(SITE_B_API_KEY="old-key-abc", SITE_B_API_KEY_NEW="new-key-xyz")
    def test_catalog_accepts_old_key_during_rotation(self):
        """
        During a rotation window, the old SITE_B_API_KEY is still accepted.
        """
        url = reverse("inventory:material-catalog")
        resp = self.client.get(
            url,
            {"email": "p5eng@example.com"},
            HTTP_X_SITE_B_API_KEY="old-key-abc",
        )
        self.assertEqual(resp.status_code, 200)

    @override_settings(SITE_B_API_KEY="old-key-abc", SITE_B_API_KEY_NEW="new-key-xyz")
    def test_catalog_accepts_new_key_during_rotation(self):
        """
        During a rotation window, the new SITE_B_API_KEY_NEW is also accepted.
        """
        url = reverse("inventory:material-catalog")
        resp = self.client.get(
            url,
            {"email": "p5eng@example.com"},
            HTTP_X_SITE_B_API_KEY="new-key-xyz",
        )
        self.assertEqual(resp.status_code, 200)

    @override_settings(SITE_B_API_KEY="old-key-abc", SITE_B_API_KEY_NEW="new-key-xyz")
    def test_catalog_rejects_unknown_key_during_rotation(self):
        """
        A request with neither old nor new key is rejected during rotation window.
        """
        url = reverse("inventory:material-catalog")
        resp = self.client.get(
            url,
            {"email": "p5eng@example.com"},
            HTTP_X_SITE_B_API_KEY="completely-wrong-key",
        )
        self.assertEqual(resp.status_code, 403)

    @override_settings(SITE_B_API_KEY="", SITE_B_API_KEY_NEW="new-key-xyz")
    def test_catalog_accepts_new_key_after_old_key_cleared(self):
        """
        After cutover (SITE_B_API_KEY cleared), only the new key works.
        """
        url = reverse("inventory:material-catalog")
        resp = self.client.get(
            url,
            {"email": "p5eng@example.com"},
            HTTP_X_SITE_B_API_KEY="new-key-xyz",
        )
        self.assertEqual(resp.status_code, 200)




