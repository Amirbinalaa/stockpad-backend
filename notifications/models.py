import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    CATEGORY_ALERT = "alert"
    CATEGORY_REMINDER = "reminder"
    CATEGORY_REQUEST = "request"

    CATEGORY_CHOICES = [
        (CATEGORY_ALERT, "Alert"),
        (CATEGORY_REMINDER, "Reminder"),
        (CATEGORY_REQUEST, "Request"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    category = models.CharField(
        max_length=10,
        choices=CATEGORY_CHOICES,
        default=CATEGORY_ALERT,
    )
    is_read = models.BooleanField(default=False)
    group_key = models.CharField(max_length=255, null=True, blank=True)
    count = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notifications_notification"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"[{self.category}] {self.title} → {self.user}"

    @classmethod
    def create_or_group(cls, user, title, message, category, group_key=None):
        """
        Idempotent notification creator with 24-hour deduplication.

        If an unread notification with the same (user, category, group_key)
        already exists and was last updated within the past 24 hours, this
        method increments its count and refreshes the message instead of
        inserting a new row.

        If no such notification exists, a fresh record is created.

        Returns the Notification instance (created or updated) and a boolean
        indicating whether a new record was created.
        """
        if group_key:
            cutoff = timezone.now() - timedelta(hours=24)
            existing = (
                cls.objects.filter(
                    user=user,
                    category=category,
                    group_key=group_key,
                    is_read=False,
                    updated_at__gte=cutoff,
                )
                .order_by("-updated_at")
                .first()
            )

            if existing:
                existing.count += 1
                existing.message = message
                existing.title = title
                existing.save(update_fields=["count", "message", "title", "updated_at"])
                return existing, False

        notification = cls.objects.create(
            user=user,
            title=title,
            message=message,
            category=category,
            group_key=group_key,
        )
        return notification, True
