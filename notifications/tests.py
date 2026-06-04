from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Notification


User = get_user_model()


class NotificationTests(TestCase):
    """
    Tests for notification list, summary, mark read, and clear all.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="notifuser", password="pass123456", role="admin"
        )
        login_resp = self.client.post(
            "/api/auth/login/",
            {"username": "notifuser", "password": "pass123456"},
            format="json",
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login_resp.data['access']}"
        )

    def _create_notifications(self):
        Notification.objects.create(
            user=self.user,
            title="Low stock",
            message="Cement is low",
            category=Notification.CATEGORY_ALERT,
        )
        Notification.objects.create(
            user=self.user,
            title="Reminder",
            message="Check inventory",
            category=Notification.CATEGORY_REMINDER,
        )
        Notification.objects.create(
            user=self.user,
            title="Request",
            message="Approve order",
            category=Notification.CATEGORY_REQUEST,
        )

    def test_list_notifications(self):
        """List all notifications for current user."""
        self._create_notifications()
        resp = self.client.get(reverse("notifications:list"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 3)

    def test_list_notifications_filtered_by_category(self):
        """Filter notifications by category query param."""
        self._create_notifications()
        resp = self.client.get(
            reverse("notifications:list") + "?category=alerts"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["category"], "alerts")

    def test_summary_counts_unread(self):
        """Summary returns counts of unread notifications by category."""
        self._create_notifications()
        resp = self.client.get(reverse("notifications:summary"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["all"], 3)
        self.assertEqual(resp.data["alerts"], 1)
        self.assertEqual(resp.data["reminders"], 1)
        self.assertEqual(resp.data["requests"], 1)

    def test_mark_notification_read(self):
        """Mark a notification as read."""
        notif = Notification.objects.create(
            user=self.user,
            title="Low stock",
            message="Cement is low",
            category=Notification.CATEGORY_ALERT,
        )
        url = reverse("notifications:mark-read", kwargs={"pk": notif.pk})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 204)

        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_mark_notification_read_not_found_for_other_user(self):
        """404 when notification does not belong to current user."""
        other = User.objects.create_user(
            username="other", password="pass123456", role="operator"
        )
        notif = Notification.objects.create(
            user=other,
            title="Other",
            message="Other notif",
            category=Notification.CATEGORY_ALERT,
        )
        url = reverse("notifications:mark-read", kwargs={"pk": notif.pk})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)

    def test_clear_all_notifications(self):
        """Delete all notifications for current user only."""
        self._create_notifications()
        other = User.objects.create_user(
            username="other", password="pass123456", role="operator"
        )
        Notification.objects.create(
            user=other,
            title="Other",
            message="Other",
            category=Notification.CATEGORY_ALERT,
        )

        resp = self.client.post(reverse("notifications:clear-all"))
        self.assertEqual(resp.status_code, 204)

        self.assertEqual(Notification.objects.filter(user=self.user).count(), 0)
        self.assertEqual(Notification.objects.filter(user=other).count(), 1)

