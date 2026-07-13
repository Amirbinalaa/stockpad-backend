from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification
from .serializers import NotificationSerializer


class NotificationListView(generics.ListAPIView):
    """
    GET /api/notifications/
    Returns all notifications for the authenticated user, ordered by
    updated_at DESC (most recently touched first).
    """

    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        category = self.request.query_params.get("category")
        qs = Notification.objects.filter(user=self.request.user)
        if category:
            # Map plural forms to singular if necessary
            mapping = {
                "alerts": Notification.CATEGORY_ALERT,
                "reminders": Notification.CATEGORY_REMINDER,
                "requests": Notification.CATEGORY_REQUEST,
            }
            mapped_category = mapping.get(category, category)
            if mapped_category in {
                Notification.CATEGORY_ALERT,
                Notification.CATEGORY_REMINDER,
                Notification.CATEGORY_REQUEST,
            }:
                qs = qs.filter(category=mapped_category)
        return qs


class NotificationCreateView(APIView):
    """
    POST /api/notifications/
    Creates a new notification (or increments an existing grouped one) using
    the smart deduplication logic in Notification.create_or_group().

    Expected JSON body:
        {
            "title":     "⚠️ Low Stock Alert",
            "message":   "Cement is at 12.5% — below the 30% threshold.",
            "category":  "alert",
            "group_key": "low-stock-cement-42"   (optional but recommended)
        }
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        title = request.data.get("title", "").strip()
        message = request.data.get("message", "").strip()
        category = request.data.get("category", "alert").strip()
        group_key = request.data.get("group_key") or None

        if not title or not message:
            return Response(
                {"detail": "Both 'title' and 'message' are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        valid_categories = {Notification.CATEGORY_ALERT, Notification.CATEGORY_REMINDER, Notification.CATEGORY_REQUEST}
        if category not in valid_categories:
            return Response(
                {"detail": f"'category' must be one of: {sorted(valid_categories)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        notification, created = Notification.create_or_group(
            user=request.user,
            title=title,
            message=message,
            category=category,
            group_key=group_key,
        )

        serializer = NotificationSerializer(notification)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class NotificationSummaryView(APIView):
    """
    GET /api/notifications/summary/
    Returns unread notification counts broken down by category.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        qs = Notification.objects.filter(user=request.user, is_read=False)

        counts = {
            "all": qs.count(),
            "alert": qs.filter(category=Notification.CATEGORY_ALERT).count(),
            "reminder": qs.filter(category=Notification.CATEGORY_REMINDER).count(),
            "request": qs.filter(category=Notification.CATEGORY_REQUEST).count(),
            "alerts": qs.filter(category=Notification.CATEGORY_ALERT).count(),
            "reminders": qs.filter(category=Notification.CATEGORY_REMINDER).count(),
            "requests": qs.filter(category=Notification.CATEGORY_REQUEST).count(),
        }
        return Response(counts)


class NotificationMarkReadView(APIView):
    """
    PATCH /api/notifications/<uuid:pk>/read/
    Marks a single notification as read.
    """

    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk, *args, **kwargs):
        try:
            notification = Notification.objects.get(pk=pk, user=request.user)
        except Notification.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        notification.is_read = True
        notification.save(update_fields=["is_read"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationMarkAllReadView(APIView):
    """
    PATCH /api/notifications/read-all/
    Marks every unread notification for the current user as read in a single
    bulk UPDATE — far more efficient than looping N individual requests.
    """

    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, *args, **kwargs):
        updated = Notification.objects.filter(
            user=request.user, is_read=False
        ).update(is_read=True)
        return Response({"updated": updated}, status=status.HTTP_200_OK)


class NotificationDeleteView(APIView):
    """
    DELETE /api/notifications/<uuid:pk>/
    Permanently removes a single notification.
    """

    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk, *args, **kwargs):
        try:
            notification = Notification.objects.get(pk=pk, user=request.user)
        except Notification.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        notification.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
