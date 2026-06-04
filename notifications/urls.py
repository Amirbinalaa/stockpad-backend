from django.urls import path

from .views import (
    NotificationClearAllView,
    NotificationListView,
    NotificationMarkReadView,
    NotificationSummaryView,
)


app_name = "notifications"

urlpatterns = [
    path("", NotificationListView.as_view(), name="list"),
    path("summary/", NotificationSummaryView.as_view(), name="summary"),
    path("<int:pk>/read/", NotificationMarkReadView.as_view(), name="mark-read"),
    path("clear-all/", NotificationClearAllView.as_view(), name="clear-all"),
]

