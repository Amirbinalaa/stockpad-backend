from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification
from .serializers import NotificationSerializer


class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        category = self.request.query_params.get("category")
        qs = Notification.objects.filter(user=self.request.user)
        if category in {
            Notification.CATEGORY_ALERT,
            Notification.CATEGORY_REMINDER,
            Notification.CATEGORY_REQUEST,
        }:
            qs = qs.filter(category=category)
        return qs


class NotificationSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        qs = Notification.objects.filter(user=user, is_read=False)

        counts = {
            "all": qs.count(),
            "alerts": qs.filter(category=Notification.CATEGORY_ALERT).count(),
            "reminders": qs.filter(category=Notification.CATEGORY_REMINDER).count(),
            "requests": qs.filter(category=Notification.CATEGORY_REQUEST).count(),
        }
        return Response(counts)


class NotificationMarkReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk, *args, **kwargs):
        try:
            notification = Notification.objects.get(pk=pk, user=request.user)
        except Notification.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        notification.is_read = True
        notification.save(update_fields=["is_read"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationClearAllView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        Notification.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

