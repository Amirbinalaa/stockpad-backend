from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Notification


User = get_user_model()


class NotificationTests(TestCase):
    """
    Tests for notification list, creation/grouping, summary, mark read, read-all, and delete.
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
        self.assertEqual(len(resp.data["results"]), 3)

    def test_list_notifications_filtered_by_category(self):
        """Filter notifications by category query param."""
        self._create_notifications()
        # Singular category
        resp = self.client.get(
            reverse("notifications:list") + "?category=alert"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 1)
        self.assertEqual(resp.data["results"][0]["category"], "alert")

        # Plural category (backward compatibility check)
        resp2 = self.client.get(
            reverse("notifications:list") + "?category=alerts"
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(len(resp2.data["results"]), 1)
        self.assertEqual(resp2.data["results"][0]["category"], "alert")

    def test_summary_counts_unread(self):
        """Summary returns counts of unread notifications by category."""
        self._create_notifications()
        resp = self.client.get(reverse("notifications:summary"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["all"], 3)
        self.assertEqual(resp.data["alert"], 1)
        self.assertEqual(resp.data["reminder"], 1)
        self.assertEqual(resp.data["request"], 1)
        # Plurals for compatibility
        self.assertEqual(resp.data["alerts"], 1)
        self.assertEqual(resp.data["reminders"], 1)
        self.assertEqual(resp.data["requests"], 1)

    def test_mark_notification_read(self):
        """Mark a notification as read (PATCH)."""
        notif = Notification.objects.create(
            user=self.user,
            title="Low stock",
            message="Cement is low",
            category=Notification.CATEGORY_ALERT,
        )
        url = reverse("notifications:mark-read", kwargs={"pk": notif.pk})
        resp = self.client.patch(url)
        self.assertEqual(resp.status_code, 204)

        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_mark_notification_read_not_found_for_other_user(self):
        """404 when notification does not belong to current user (PATCH)."""
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
        resp = self.client.patch(url)
        self.assertEqual(resp.status_code, 404)

    def test_delete_notification(self):
        """Delete a notification entirely."""
        notif = Notification.objects.create(
            user=self.user,
            title="Low stock",
            message="Cement is low",
            category=Notification.CATEGORY_ALERT,
        )
        url = reverse("notifications:delete", kwargs={"pk": notif.pk})
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Notification.objects.filter(pk=notif.pk).exists())

    def test_mark_all_unread_as_read(self):
        """Mark all unread notifications for authenticated user as read."""
        self._create_notifications()
        url = reverse("notifications:mark-all-read")
        resp = self.client.patch(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Notification.objects.filter(user=self.user, is_read=False).count(), 0)

    def test_smart_grouping_create_or_group(self):
        """Smart grouping increments count and updates message within 24h."""
        notif, created1 = Notification.create_or_group(
            user=self.user,
            title="Low stock Cement",
            message="Cement is at 10%",
            category="alert",
            group_key="low-stock-cement",
        )
        self.assertTrue(created1)
        self.assertEqual(notif.count, 1)

        notif_updated, created2 = Notification.create_or_group(
            user=self.user,
            title="Low stock Cement",
            message="Cement and 1 other item are low",
            category="alert",
            group_key="low-stock-cement",
        )
        self.assertFalse(created2)
        self.assertEqual(notif_updated.pk, notif.pk)
        self.assertEqual(notif_updated.count, 2)
        self.assertEqual(notif_updated.message, "Cement and 1 other item are low")
