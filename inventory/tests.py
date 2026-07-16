from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
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

    @patch("requests.post")
    def test_create_material_request_success_and_webhook(self, mock_post):
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

    @patch("requests.post")
    def test_create_material_request_fallback_superuser(self, mock_post):
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

    @patch("requests.post")
    def test_review_material_request_webhook(self, mock_post):
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

    @patch("requests.post")
    def test_request_creation_security_enforcement(self, mock_post):
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


