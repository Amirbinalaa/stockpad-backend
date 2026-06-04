from django.conf import settings
from django.db import models


class Notification(models.Model):
    CATEGORY_ALERT = "alerts"
    CATEGORY_REMINDER = "reminders"
    CATEGORY_REQUEST = "requests"

    CATEGORY_CHOICES = [
        (CATEGORY_ALERT, "Alert"),
        (CATEGORY_REMINDER, "Reminder"),
        (CATEGORY_REQUEST, "Request"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default=CATEGORY_ALERT,
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

