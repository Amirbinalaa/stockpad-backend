from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import UserPreference


User = get_user_model()


class UserPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPreference
        fields = ["default_unit", "date_format", "theme", "dead_stock_threshold_days"]


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name"]

