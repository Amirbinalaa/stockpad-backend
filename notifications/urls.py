from django.urls import path

from .views import (
    NotificationCreateView,
    NotificationDeleteView,
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationMarkReadView,
    NotificationSummaryView,
)


app_name = "notifications"

urlpatterns = [
    # List all notifications for the current user
    path("", NotificationListView.as_view(), name="list"),

    # Create a notification (with backend deduplication via group_key)
    path("create/", NotificationCreateView.as_view(), name="create"),

    # Unread count summary per category
    path("summary/", NotificationSummaryView.as_view(), name="summary"),

    # Mark all unread as read (single bulk PATCH — no looping needed)
    path("read-all/", NotificationMarkAllReadView.as_view(), name="mark-all-read"),

    # Single-notification actions (UUID pk)
    path("<uuid:pk>/read/", NotificationMarkReadView.as_view(), name="mark-read"),
    path("<uuid:pk>/", NotificationDeleteView.as_view(), name="delete"),
]
