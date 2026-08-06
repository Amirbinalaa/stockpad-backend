from django.contrib.auth import get_user_model
from django.db import connection
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import UserPreference
from .serializers import AccountSerializer, UserPreferenceSerializer


User = get_user_model()


class HealthCheckView(APIView):
    """Lightweight health probe that verifies database connectivity."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as exc:
            return Response(
                {"status": "unhealthy", "detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"status": "healthy"}, status=status.HTTP_200_OK)


class AccountView(generics.RetrieveAPIView):
    serializer_class = AccountSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class UserPreferenceView(generics.RetrieveUpdateAPIView):
    serializer_class = UserPreferenceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        preference, _ = UserPreference.objects.get_or_create(user=self.request.user)
        return preference

