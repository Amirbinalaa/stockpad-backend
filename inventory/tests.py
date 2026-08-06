from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Material, StockTransaction, EngineerConnection
from .material_categories import (
    CATEGORY_BUILDING,
    CATEGORY_STEEL,
    infer_category_from_name,
    resolve_material_category_name,
)



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
        errors = resp.data.get("errors", resp.data)
        self.assertIn("quantity", errors)

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



class MaterialCategoryInferenceTests(TestCase):
    """Keyword-based category inference for uncategorized materials."""

    def test_cement_infers_building_materials(self):
        self.assertEqual(infer_category_from_name("Portland Cement"), CATEGORY_BUILDING)

    def test_bolts_infers_steel_and_metal(self):
        self.assertEqual(infer_category_from_name("Hex Bolts M8"), CATEGORY_STEEL)

    def test_explicit_category_is_preserved(self):
        self.assertEqual(
            resolve_material_category_name(name="Random Item", explicit_category="Finishing"),
            "Finishing",
        )

    def test_uncategorized_falls_back_to_inference(self):
        self.assertEqual(
            resolve_material_category_name(name="cement bag", explicit_category=""),
            CATEGORY_BUILDING,
        )
        self.assertEqual(
            resolve_material_category_name(name="cement bag", explicit_category="Uncategorized"),
            CATEGORY_BUILDING,
        )


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
        self.assertEqual(item["category_name"], "Building Materials")
        self.assertEqual(item["category"]["name"], "Building Materials")

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


# ---------------------------------------------------------------------------
# Phase 1 — Product & ProductMaterial (BOM) model tests
# ---------------------------------------------------------------------------
from django.db import IntegrityError
from django.db.models import ProtectedError

from .models import Product, ProductMaterial


class ProductModelTests(TestCase):
    """
    Unit tests for Product and ProductMaterial model constraints.
    No views / serializers — pure model-layer assertions.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="prodtestuser", password="pass123456", role="admin"
        )

    def _make_material(self, name="Steel", unit="kg"):
        return Material.objects.create(
            user=self.user,
            name=name,
            unit=unit,
        )

    def _make_product(self, name="Bolt", sku="SKU-001", uom="pcs"):
        return Product.objects.create(
            name=name,
            sku=sku,
            unit_of_measure=uom,
        )

    # ------------------------------------------------------------------
    # Test 1 — SKU uniqueness enforced at the DB level
    # ------------------------------------------------------------------
    def test_product_sku_unique(self):
        """Two products with the same SKU must raise IntegrityError."""
        self._make_product(name="ProductA", sku="DUP-SKU")
        with self.assertRaises(IntegrityError):
            Product.objects.create(
                name="ProductB",
                sku="DUP-SKU",
                unit_of_measure="pcs",
            )

    # ------------------------------------------------------------------
    # Test 2 — BOM unique_together (product, material)
    # ------------------------------------------------------------------
    def test_bom_unique_together(self):
        """Duplicate (product, material) in BOM must raise IntegrityError."""
        product = self._make_product()
        material = self._make_material()

        ProductMaterial.objects.create(
            product=product,
            material=material,
            quantity_per_unit="2.500",
        )
        with self.assertRaises(IntegrityError):
            ProductMaterial.objects.create(
                product=product,
                material=material,
                quantity_per_unit="1.000",
            )

    # ------------------------------------------------------------------
    # Test 3 — quantity_per_unit stores Decimal (including fractions)
    # ------------------------------------------------------------------
    def test_bom_decimal_precision(self):
        """quantity_per_unit stores fractional Decimal values accurately."""
        from decimal import Decimal

        product = self._make_product()
        material = self._make_material()

        line = ProductMaterial.objects.create(
            product=product,
            material=material,
            quantity_per_unit="0.500",
        )
        line.refresh_from_db()
        self.assertEqual(line.quantity_per_unit, Decimal("0.500"))

        # Also verify 3 decimal places are retained
        line.quantity_per_unit = Decimal("12.345")
        line.save()
        line.refresh_from_db()
        self.assertEqual(line.quantity_per_unit, Decimal("12.345"))

    # ------------------------------------------------------------------
    # Test 4 — Deleting a Product cascades to its BOM lines
    # ------------------------------------------------------------------
    def test_product_delete_cascades_bom_lines(self):
        """Deleting a Product removes all associated ProductMaterial rows."""
        product = self._make_product()
        material = self._make_material()

        line = ProductMaterial.objects.create(
            product=product,
            material=material,
            quantity_per_unit="1.000",
        )
        line_id = line.pk

        product.delete()
        self.assertFalse(ProductMaterial.objects.filter(pk=line_id).exists())

    # ------------------------------------------------------------------
    # Test 5 — Deleting a Material referenced in a BOM raises ProtectedError
    # ------------------------------------------------------------------
    def test_material_delete_protected_by_bom(self):
        """Deleting a Material used in a BOM line must raise ProtectedError."""
        product = self._make_product()
        material = self._make_material()

        ProductMaterial.objects.create(
            product=product,
            material=material,
            quantity_per_unit="3.000",
        )

        with self.assertRaises(ProtectedError):
            material.delete()

        # Material must still exist in the database
        self.assertTrue(Material.objects.filter(pk=material.pk).exists())


# ---------------------------------------------------------------------------
# Phase 3 — Product & BOM API Endpoint Tests
# ---------------------------------------------------------------------------
class ProductApiTests(TestCase):
    """
    API integration tests for Product CRUD, BOM management, and Material Quick-Create.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="wmuser", password="password123", role="admin"
        )
        self.client.force_authenticate(user=self.user)

        self.mat1 = Material.objects.create(
            user=self.user, name="Oak Wood", unit="m", current_quantity=Decimal("100.00")
        )
        self.mat2 = Material.objects.create(
            user=self.user, name="Varnish", unit="L", current_quantity=Decimal("50.00")
        )

    def test_create_product_with_nested_bom(self):
        """POST /api/inventory/products/ creates a product and nested BOM lines."""
        url = reverse("inventory:product-list-create")
        payload = {
            "name": "Dining Table",
            "sku": "TAB-OAK-001",
            "category": "Furniture",
            "unit_of_measure": "set",
            "status": "active",
            "description": "Solid oak dining table",
            "bom_lines": [
                {"material": self.mat1.id, "quantity_per_unit": "5.000"},
                {"material": self.mat2.id, "quantity_per_unit": "0.750"},
            ],
        }
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["sku"], "TAB-OAK-001")
        self.assertEqual(len(response.data["bom_lines"]), 2)

        # Verify DB records created
        product = Product.objects.get(sku="TAB-OAK-001")
        self.assertEqual(product.bom_lines.count(), 2)

    def test_create_product_duplicate_material_bom_error(self):
        """POST /api/inventory/products/ with duplicate material in BOM lines returns 400."""
        url = reverse("inventory:product-list-create")
        payload = {
            "name": "Invalid Chair",
            "sku": "CHR-DUP-001",
            "unit_of_measure": "pcs",
            "bom_lines": [
                {"material": self.mat1.id, "quantity_per_unit": "2.000"},
                {"material": self.mat1.id, "quantity_per_unit": "1.000"},
            ],
        }
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 400)
        errors = response.data.get("errors", response.data)
        self.assertIn("bom_lines", errors)

    def test_create_product_duplicate_sku_error(self):
        """POST /api/inventory/products/ with duplicate SKU returns 400."""
        Product.objects.create(name="Exist Table", sku="EXIST-SKU", unit_of_measure="pcs")
        url = reverse("inventory:product-list-create")
        payload = {
            "name": "New Table",
            "sku": "EXIST-SKU",
            "unit_of_measure": "pcs",
        }
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 400)

    def test_product_bom_put_full_replace(self):
        """PUT /api/inventory/products/<id>/bom/ wipes existing BOM lines and replaces them."""
        product = Product.objects.create(name="Desk", sku="DESK-01", unit_of_measure="pcs")
        ProductMaterial.objects.create(product=product, material=self.mat1, quantity_per_unit=Decimal("2.000"))

        url = reverse("inventory:product-bom", kwargs={"pk": product.pk})
        new_payload = [
            {"material": self.mat2.id, "quantity_per_unit": "1.500"}
        ]
        response = self.client.put(url, data=new_payload, format="json")
        self.assertEqual(response.status_code, 200)

        # Mat1 should be removed, Mat2 should remain
        lines = ProductMaterial.objects.filter(product=product)
        self.assertEqual(lines.count(), 1)
        self.assertEqual(lines.first().material, self.mat2)

    def test_product_bom_patch_incremental_upsert(self):
        """PATCH /api/inventory/products/<id>/bom/ adds or updates lines without deleting omitted ones."""
        product = Product.objects.create(name="Desk", sku="DESK-02", unit_of_measure="pcs")
        ProductMaterial.objects.create(product=product, material=self.mat1, quantity_per_unit=Decimal("2.000"))

        url = reverse("inventory:product-bom", kwargs={"pk": product.pk})
        patch_payload = [
            {"material": self.mat2.id, "quantity_per_unit": "0.500"}
        ]
        response = self.client.patch(url, data=patch_payload, format="json")
        self.assertEqual(response.status_code, 200)

        # Both Mat1 and Mat2 should be in BOM
        lines = ProductMaterial.objects.filter(product=product)
        self.assertEqual(lines.count(), 2)

    def test_material_quick_create_success(self):
        """POST /api/inventory/materials/quick-create/ creates material with initial_quantity=0."""
        url = reverse("inventory:material-quick-create")
        payload = {"name": "Brass Screws", "unit": "pcs"}
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["name"], "Brass Screws")
        self.assertEqual(response.data["unit"], "pcs")

        # Check DB record
        mat = Material.objects.get(name="Brass Screws", user=self.user)
        self.assertEqual(mat.current_quantity, Decimal("0.00"))

    def test_material_quick_create_case_insensitive_duplicate_error(self):
        """POST /api/inventory/materials/quick-create/ with existing name (case-insensitive) returns 400."""
        url = reverse("inventory:material-quick-create")
        payload = {"name": "oak wood", "unit": "m"}
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 400)
        errors = response.data.get("errors", response.data)
        self.assertIn("name", errors)


# ---------------------------------------------------------------------------
# Phase 4 — Implied Demand Insights API Tests
# ---------------------------------------------------------------------------
class Phase4ImpliedDemandApiTests(TestCase):
    """
    Unit tests for Phase 4 Implied Demand Insights calculation and API endpoint.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="demand_user", password="password123", role="admin"
        )
        self.user2 = User.objects.create_user(
            username="other_user", password="password123", role="admin"
        )
        self.client.force_authenticate(user=self.user)

        # Create materials for user
        self.mat_wood = Material.objects.create(
            user=self.user, name="Oak Wood", unit="kg", current_quantity=Decimal("500.00")
        )
        self.mat_glue = Material.objects.create(
            user=self.user, name="Wood Glue", unit="L", current_quantity=Decimal("100.00")
        )

        # Create StockTransaction OUT records (50 kg Wood out, 10 L Glue out)
        StockTransaction.objects.create(
            material=self.mat_wood,
            type=StockTransaction.TYPE_OUT,
            quantity=Decimal("50.00"),
            performed_by=self.user,
        )
        StockTransaction.objects.create(
            material=self.mat_glue,
            type=StockTransaction.TYPE_OUT,
            quantity=Decimal("10.00"),
            performed_by=self.user,
        )

        # Create Product 1 ("Dining Table")
        # BOM: Wood 5 kg/unit, Glue 0.5 L/unit
        # Wood ratio = 50 / 5 = 10
        # Glue ratio = 10 / 0.5 = 20
        # Implied Demand = 10 + 20 = 30.0
        self.prod_table = Product.objects.create(
            name="Dining Table", sku="TAB-001", unit_of_measure="pcs", status=Product.STATUS_ACTIVE
        )
        ProductMaterial.objects.create(
            product=self.prod_table, material=self.mat_wood, quantity_per_unit=Decimal("5.000")
        )
        ProductMaterial.objects.create(
            product=self.prod_table, material=self.mat_glue, quantity_per_unit=Decimal("0.500")
        )

        # Create Product 2 ("Wooden Box")
        # BOM: Wood 25 kg/unit
        # Wood ratio = 50 / 25 = 2.0
        # Implied Demand = 2.0
        self.prod_box = Product.objects.create(
            name="Wooden Box", sku="BOX-001", unit_of_measure="pcs", status=Product.STATUS_ACTIVE
        )
        ProductMaterial.objects.create(
            product=self.prod_box, material=self.mat_wood, quantity_per_unit=Decimal("25.000")
        )

        # Create Product 3 ("Empty BOM Product")
        # BOM: empty -> Implied Demand = 0.0
        self.prod_empty = Product.objects.create(
            name="Empty Product", sku="EMP-001", unit_of_measure="pcs", status=Product.STATUS_ACTIVE
        )

    def test_implied_demand_calculation_and_labeling(self):
        """GET /api/inventory/products/insights/implied-demand/ calculates correct sum-ratios and labels."""
        url = reverse("inventory:product-implied-demand-insights")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["metric_label"], "Implied Demand (estimate)")
        self.assertEqual(response.data["label"], "Implied Demand (estimate)")

        results = response.data["results"]
        self.assertGreaterEqual(len(results), 3)

        # Product 1 ("Dining Table") must be ranked #1 with 30.0
        table_item = results[0]
        self.assertEqual(table_item["name"], "Dining Table")
        self.assertEqual(table_item["implied_demand"], 30.0)
        self.assertEqual(table_item["implied_demand_label"], "Implied Demand (estimate)")

        # Product 2 ("Wooden Box") must be ranked #2 with 2.0
        box_item = results[1]
        self.assertEqual(box_item["name"], "Wooden Box")
        self.assertEqual(box_item["implied_demand"], 2.0)
        self.assertEqual(box_item["implied_demand_label"], "Implied Demand (estimate)")

        # Product 3 ("Empty Product") must have implied demand = 0.0
        empty_item = results[2]
        self.assertEqual(empty_item["name"], "Empty Product")
        self.assertEqual(empty_item["implied_demand"], 0.0)

    def test_implied_demand_limit_param(self):
        """GET request respects limit parameter."""
        url = reverse("inventory:product-implied-demand-insights")
        response = self.client.get(url, {"limit": "2"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertEqual(response.data["limit"], 2)

    def test_implied_demand_period_param(self):
        """GET request respects period filtering (e.g. 7days vs 30days)."""
        # Create an old transaction 40 days ago (outside 30days window)
        old_time = timezone.now() - timezone.timedelta(days=40)
        tx = StockTransaction.objects.create(
            material=self.mat_wood,
            type=StockTransaction.TYPE_OUT,
            quantity=Decimal("100.00"),
            performed_by=self.user,
        )
        # Manually update created_at to old_time
        StockTransaction.objects.filter(pk=tx.pk).update(created_at=old_time)

        url = reverse("inventory:product-implied-demand-insights")
        
        # 30 days query ignores the 40-day-old transaction (50 out -> demand for Box is 50/25 = 2.0)
        resp_30 = self.client.get(url, {"period": "30days"})
        box_30 = next(i for i in resp_30.data["results"] if i["sku"] == "BOX-001")
        self.assertEqual(box_30["implied_demand"], 2.0)

        # 90 days query includes the 40-day-old transaction (150 out -> demand for Box is 150/25 = 6.0)
        resp_90 = self.client.get(url, {"period": "90days"})
        box_90 = next(i for i in resp_90.data["results"] if i["sku"] == "BOX-001")
        self.assertEqual(box_90["implied_demand"], 6.0)

    def test_user_isolation(self):
        """Transactions belonging to another user are excluded from calculation."""
        # Create material and transaction for user2
        mat_u2 = Material.objects.create(
            user=self.user2, name="Other Wood", unit="kg", current_quantity=Decimal("1000.00")
        )
        StockTransaction.objects.create(
            material=mat_u2,
            type=StockTransaction.TYPE_OUT,
            quantity=Decimal("5000.00"),
            performed_by=self.user2,
        )

        # Authenticate as user1 (self.user)
        url = reverse("inventory:product-implied-demand-insights")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        table_item = next(i for i in response.data["results"] if i["sku"] == "TAB-001")
        # Should still be 30.0, unaffected by user2's 5000.0 out transaction
        self.assertEqual(table_item["implied_demand"], 30.0)



