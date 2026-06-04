from datetime import timedelta

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken


User = get_user_model()


class StockPadTokenObtainPairSerializer(TokenObtainPairSerializer):
    remember_me = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        remember_me = attrs.pop("remember_me", False)
        username = (attrs.get("username") or "").strip()
        if "@" in username:
            matched = User.objects.filter(email__iexact=username).first()
            if matched:
                attrs["username"] = matched.username
        data = super().validate(attrs)

        refresh = RefreshToken.for_user(self.user)
        lifetime = timedelta(hours=1) if remember_me else timedelta(minutes=15)
        refresh.set_exp(lifetime=lifetime)
        access = refresh.access_token
        access.set_exp(lifetime=lifetime)

        data["refresh"] = str(refresh)
        data["access"] = str(access)
        data["remember_me"] = remember_me

        request = self.context.get("request")
        if request is not None:
            from django.contrib.auth import login

            login(request, self.user)
            request.session.set_expiry(3600 if remember_me else 0)

        return data
