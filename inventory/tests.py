from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Material, StockTransaction


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
        
        # Verify webhook was POSTed
        mock_post.assert_called_once_with(
            "https://site-b.com/webhooks/requests/",
            json={"id": req.id, "status": "pending"},
            timeout=5
        )

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
        
        # Verify webhook POSTed
        mock_post.assert_called_once_with(
            "https://site-b.com/webhooks/requests/",
            json={"id": req.id, "status": "approved"},
            timeout=5
        )

