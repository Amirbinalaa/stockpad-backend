from django.contrib.auth import get_user_model
from rest_framework import generics, permissions

from .models import UserPreference
from .serializers import AccountSerializer, UserPreferenceSerializer


User = get_user_model()


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

