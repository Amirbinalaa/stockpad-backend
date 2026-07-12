# pyrefly: ignore [missing-import]
import os
from urllib.parse import quote

from django.contrib.auth import get_user_model
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from datetime import timedelta
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.core.mail import send_mail
from django.conf import settings
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import (
    ChangePasswordSerializer,
    RegisterSerializer,
    UserSerializer,
)
from .token_serializers import StockPadTokenObtainPairSerializer
from .auth_utils import (
    content_file_from_data_url,
    normalize_reset_email,
    normalize_reset_token,
)


User = get_user_model()


def _apply_password_reset(user, new_password: str) -> None:
    try:
        password_validation.validate_password(new_password, user)
    except ValidationError as exc:
        raise ValueError("; ".join(exc.messages)) from exc
    user.set_password(new_password)
    user.save(update_fields=["password"])
    user.refresh_from_db()
    if not user.check_password(new_password):
        raise ValueError("Password could not be saved.")

# Production default points to Vercel. Override locally with:
#   FRONTEND_RESET_BASE_URL=http://127.0.0.1:5500  (in your .env)
FRONTEND_RESET_BASE = os.environ.get(
    "FRONTEND_RESET_BASE_URL",
    "https://stockpad-smoky.vercel.app",
).rstrip("/")


def _blacklist_user_tokens(user):
    try:
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )

        for outstanding in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=outstanding)
    except Exception:
        pass


class RegisterView(generics.CreateAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context


class ChangePasswordView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        old_password = serializer.validated_data["old_password"]
        new_password = serializer.validated_data["new_password"]

        if not user.check_password(old_password):
            return Response(
                {"detail": "Old password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LoginView(TokenObtainPairView):
    """JWT login with optional remember_me (1-hour session)."""
    serializer_class = StockPadTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        if request.data.get("credential"):
            return GoogleAuthView().post(request)
        return super().post(request, *args, **kwargs)


class RefreshView(TokenRefreshView):
    """
    JWT token refresh view.
    """


class ProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    http_method_names = ['get', 'patch']

    def get_object(self):
        return self.request.user

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context


class ProfilePictureUploadView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, *args, **kwargs):
        image = (
            request.FILES.get("image")
            or request.FILES.get("file")
            or request.FILES.get("profile_picture")
        )

        if not image:
            raw_payload = (
                request.data.get("image")
                or request.data.get("file")
                or request.data.get("profile_picture")
            )
            if isinstance(raw_payload, str) and raw_payload.strip().startswith("data:image/"):
                try:
                    image = content_file_from_data_url(raw_payload)
                except ValueError as exc:
                    return Response(
                        {"detail": str(exc)},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            elif isinstance(raw_payload, str) and raw_payload.strip():
                return Response(
                    {"detail": "Expected a file upload or a data:image/...;base64, URL."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if not image:
            return Response(
                {"detail": "No image file provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if image.size > 2 * 1024 * 1024:
            return Response(
                {"detail": "Image must be under 2MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        try:
            if user.profile_picture:
                user.profile_picture.delete(save=False)
            user.profile_picture = image
            user.save(update_fields=["profile_picture"])
        except Exception as exc:
            return Response(
                {"detail": f"Could not save profile picture: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        url = request.build_absolute_uri(user.profile_picture.url)
        return Response({"profile_picture_url": url}, status=status.HTTP_200_OK)


class LogoutView(APIView):
    def post(self, request, *args, **kwargs):
        try:
            # Simply return success - JWT tokens are stateless
            # Frontend will handle token removal
            return Response(
                {"detail": "Successfully logged out"},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ForgotPasswordView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        if not email:
            return Response(
                {"detail": "Email is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        generic = {
            "detail": "If an account exists for this email, a reset link has been sent."
        }

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response(generic)

        token = default_token_generator.make_token(user)
        reset_url = (
            f"{FRONTEND_RESET_BASE}/reset-password.html"
            f"?token={token}&email={quote(user.email)}"
        )

        send_mail(
            subject="StockPad — Reset your password",
            message=(
                f"Hi {user.username},\n\n"
                f"Click the link below to reset your password:\n\n{reset_url}\n\n"
                "This link expires in 24 hours.\n\n"
                "If you did not request this, ignore this email."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )

        return Response(generic)


class ResetPasswordView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        uid = request.data.get('uid')
        token = request.data.get('token')
        new_password = request.data.get('new_password')

        if not all([uid, token, new_password]):
            return Response(
                {'detail': 'All fields are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError):
            return Response(
                {'detail': 'Invalid reset link.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        token = normalize_reset_token(token)
        if not default_token_generator.check_token(user, token):
            return Response(
                {'detail': 'Reset link has expired or is invalid.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                _apply_password_reset(user, new_password)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        _blacklist_user_tokens(user)
        return Response({"detail": "Password reset successfully."})


class ResetPasswordConfirmView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = normalize_reset_email(request.data.get("email"))
        token = normalize_reset_token(request.data.get("token"))
        new_password = request.data.get("new_password")

        if not all([email, token, new_password]):
            return Response(
                {"detail": "All fields are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response(
                {"detail": "Invalid reset link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not default_token_generator.check_token(user, token):
            return Response(
                {"detail": "Reset link has expired or is invalid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                _apply_password_reset(user, new_password)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        _blacklist_user_tokens(user)
        return Response({"detail": "Password reset successfully."})



class GoogleAuthView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({'detail': 'Google Auth Callback Endpoint Active.'}, status=status.HTTP_200_OK)

    def post(self, request):
        token = request.data.get('credential')
        is_access_token = request.data.get('isAccessToken', False)

        if not token:
            return Response({'detail': 'Token is required.'}, status=status.HTTP_400_BAD_REQUEST)

        client_id = (settings.GOOGLE_CLIENT_ID or "").strip()
        if not client_id:
            return Response({"detail": "Google sign-in is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            if is_access_token:
                import requests as http_requests
                r = http_requests.get(
                    'https://www.googleapis.com/oauth2/v3/userinfo',
                    headers={'Authorization': f'Bearer {token}'},
                    timeout=10,
                )
                if r.status_code != 200:
                    return Response({"detail": "Invalid Google access token."}, status=status.HTTP_401_UNAUTHORIZED)
                idinfo = r.json()
            else:
                idinfo = id_token.verify_oauth2_token(
                    token, google_requests.Request(), client_id,
                )

            if not idinfo.get("email_verified"):
                return Response({"detail": "Google email is not verified."}, status=status.HTTP_401_UNAUTHORIZED)

            email = (idinfo.get('email') or '').strip().lower()
            if not email:
                return Response({"detail": "Google account has no email."}, status=status.HTTP_400_BAD_REQUEST)

            name = idinfo.get('name', '')

            try:
                user = User.objects.get(email__iexact=email)
            except User.DoesNotExist:
                username = email.split('@')[0]
                base_username = username
                counter = 1
                while User.objects.filter(username=username).exists():
                    username = f"{base_username}{counter}"
                    counter += 1
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    first_name=name.split(' ')[0] if name else '',
                    last_name=' '.join(name.split(' ')[1:]) if name else '',
                )

            remember_me = bool(request.data.get("remember_me", False))
            refresh = RefreshToken.for_user(user)
            lifetime = timedelta(hours=1) if remember_me else timedelta(minutes=15)
            refresh.set_exp(lifetime=lifetime)
            access = refresh.access_token
            access.set_exp(lifetime=lifetime)

            from django.contrib.auth import login
            login(request, user)
            request.session.set_expiry(3600 if remember_me else 0)

            return Response({
                'access': str(access),
                'refresh': str(refresh),
                'remember_me': remember_me,
                'user': UserSerializer(user, context={"request": request}).data,
            })

        except ValueError as exc:
            return Response({"detail": f"Invalid Google token: {exc}"}, status=status.HTTP_401_UNAUTHORIZED)