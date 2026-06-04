from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import UserPreference


User = get_user_model()


class SettingsTests(TestCase):
    """
    Tests for account and user preference APIs.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="setuser",
            email="set@example.com",
            first_name="Set",
            last_name="User",
            password="pass123456",
            role="manager",
        )
        login_resp = self.client.post(
            "/api/auth/login/",
            {"username": "setuser", "password": "pass123456"},
            format="json",
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login_resp.data['access']}"
        )

    def test_get_account_info(self):
        """/account returns basic user details."""
        resp = self.client.get(reverse("settings_app:account"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["username"], "setuser")
        self.assertEqual(resp.data["email"], "set@example.com")

    def test_get_preferences_creates_default(self):
        """First GET /preferences creates a UserPreference with defaults."""
        self.assertFalse(UserPreference.objects.filter(user=self.user).exists())
        resp = self.client.get(reverse("settings_app:preferences"))
        self.assertEqual(resp.status_code, 200)

        pref = UserPreference.objects.get(user=self.user)
        self.assertEqual(pref.default_unit, "kg")
        self.assertIn(resp.data["default_unit"], ["kg", "L", "pcs"])

    def test_update_preferences(self):
        """PATCH /preferences updates fields."""
        self.client.get(reverse("settings_app:preferences"))

        resp = self.client.patch(
            reverse("settings_app:preferences"),
            {
                "default_unit": "pcs",
                "date_format": "MM/DD/YYYY",
                "theme": "dark",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

        pref = UserPreference.objects.get(user=self.user)
        self.assertEqual(pref.default_unit, "pcs")
        self.assertEqual(pref.date_format, "MM/DD/YYYY")
        self.assertEqual(pref.theme, "dark")

    def test_preferences_requires_auth(self):
        """Anonymous user cannot access preferences endpoint."""
        anon = APIClient()
        resp = anon.get(reverse("settings_app:preferences"))
        self.assertEqual(resp.status_code, 401)

