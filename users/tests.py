from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.urls import reverse
from django.test import TestCase
from rest_framework.test import APIClient


User = get_user_model()


class AuthTests(TestCase):
    """
    Tests for registration, login, JWT, change password, and /me.
    """

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def test_register_success(self):
        """Register a new user with valid data."""
        url = reverse("users:register")
        payload = {
            "username": "newuser",
            "email": "new@example.com",
            "first_name": "New",
            "last_name": "User",
            "password": "StrongPass123!",
            "password2": "StrongPass123!",
        }
        resp = self.client.post(url, payload, format="json")

        self.assertEqual(resp.status_code, 201)
        self.assertTrue(User.objects.filter(username="newuser").exists())

    def test_register_password_mismatch(self):
        """Fail register when password and password2 do not match."""
        url = reverse("users:register")
        payload = {
            "username": "newuser",
            "email": "new@example.com",
            "password": "StrongPass123!",
            "password2": "Different123!",
        }
        resp = self.client.post(url, payload, format="json")

        self.assertEqual(resp.status_code, 400)
        errors = resp.data.get("errors", resp.data)
        self.assertIn("password", errors)

    def _create_user(self, username="user1", password="pass123456", role="admin"):
        user = User(username=username, role=role)
        user.set_password(password)
        user.save()
        return user

    def test_login_success_and_tokens(self):
        """Return access and refresh tokens on valid login."""
        self._create_user()
        url = reverse("users:login")
        resp = self.client.post(
            url, {"username": "user1", "password": "pass123456"}, format="json"
        )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)

    def test_login_invalid_credentials(self):
        """Reject login with wrong password."""
        self._create_user()
        url = reverse("users:login")
        resp = self.client.post(
            url, {"username": "user1", "password": "wrongpass"}, format="json"
        )

        self.assertEqual(resp.status_code, 401)

    def test_me_returns_current_user(self):
        """/me endpoint returns the authenticated user's data."""
        self._create_user()
        login_resp = self.client.post(
            reverse("users:login"),
            {"username": "user1", "password": "pass123456"},
            format="json",
        )
        access = login_resp.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        me_url = reverse("users:me")
        resp = self.client.get(me_url)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["username"], "user1")

    def test_refresh_token(self):
        """Issue a new access token when refresh token is valid."""
        self._create_user()
        login_resp = self.client.post(
            reverse("users:login"),
            {"username": "user1", "password": "pass123456"},
            format="json",
        )
        refresh = login_resp.data["refresh"]

        refresh_resp = self.client.post(
            reverse("users:token_refresh"),
            {"refresh": refresh},
            format="json",
        )

        self.assertEqual(refresh_resp.status_code, 200)
        self.assertIn("access", refresh_resp.data)

    def test_change_password_success(self):
        """Change password when old password is correct."""
        self._create_user(password="oldpass123")
        login_resp = self.client.post(
            reverse("users:login"),
            {"username": "user1", "password": "oldpass123"},
            format="json",
        )
        access = login_resp.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        resp = self.client.post(
            reverse("users:change_password"),
            {"old_password": "oldpass123", "new_password": "Newpass123!"},
            format="json",
        )

        self.assertEqual(resp.status_code, 204)

        # New login with updated password should work
        self.client.credentials()
        login_resp2 = self.client.post(
            reverse("users:login"),
            {"username": "user1", "password": "Newpass123!"},
            format="json",
        )
        self.assertEqual(login_resp2.status_code, 200)

    def test_change_password_wrong_old(self):
        """Reject change when old password is incorrect."""
        self._create_user(password="oldpass123")
        login_resp = self.client.post(
            reverse("users:login"),
            {"username": "user1", "password": "oldpass123"},
            format="json",
        )
        access = login_resp.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        resp = self.client.post(
            reverse("users:change_password"),
            {"old_password": "wrong", "new_password": "Newpass123!"},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)

    def test_reset_password_confirm_updates_password(self):
        user = User.objects.create_user(
            username="resetme",
            email="resetme@example.com",
            password="Oldpass123!",
        )
        token = default_token_generator.make_token(user)
        url = reverse("users:reset_password_confirm")
        resp = self.client.post(
            url,
            {
                "email": user.email,
                "token": token,
                "new_password": "Newpass456!",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password("Newpass456!"))
        self.assertFalse(user.check_password("Oldpass123!"))
        self.assertFalse(default_token_generator.check_token(user, token))

        login_resp = self.client.post(
            reverse("users:login"),
            {"username": "resetme", "password": "Newpass456!"},
            format="json",
        )
        self.assertEqual(login_resp.status_code, 200)


class AuthSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def test_forgot_password_missing_email_returns_400(self):
        resp = self.client.post(reverse("users:forgot_password"), {}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("detail", resp.data)

    def test_validation_error_has_uniform_shape(self):
        url = reverse("users:register")
        resp = self.client.post(
            url,
            {
                "username": "x",
                "email": "bad",
                "password": "short",
                "password2": "short",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("detail", resp.data)
        self.assertIn("errors", resp.data)

    def test_login_rate_limited(self):
        from unittest.mock import patch

        from users.views import LoginRateThrottle

        cache.clear()
        user = User(username="throttleuser", role="admin")
        user.set_password("pass123456")
        user.save()
        url = reverse("users:login")

        with patch.object(LoginRateThrottle, "get_rate", return_value="1/min"):
            self.client.post(
                url,
                {"username": "throttleuser", "password": "wrong"},
                format="json",
            )
            resp = self.client.post(
                url,
                {"username": "throttleuser", "password": "wrong"},
                format="json",
            )

        self.assertEqual(resp.status_code, 429)
        self.assertIn("detail", resp.data)

    def tearDown(self):
        cache.clear()
