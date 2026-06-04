from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from . import views

app_name = 'users'

urlpatterns = [
    path('login/', views.LoginView.as_view(), name='login'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('me/', views.MeView.as_view(), name='me'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('profile-picture/', views.ProfilePictureUploadView.as_view(), name='profile_picture'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('change-password/', views.ChangePasswordView.as_view(), name='change_password'),
    path('token/', views.LoginView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('forgot-password/', views.ForgotPasswordView.as_view(), name='forgot_password'),
    path('reset-password/', views.ResetPasswordView.as_view(), name='reset_password'),
    path(
        'reset-password-confirm/',
        views.ResetPasswordConfirmView.as_view(),
        name='reset_password_confirm',
    ),
    # Google OAuth
    path('google/', views.GoogleAuthView.as_view(), name='google_auth'),
    path('google/callback/', views.GoogleAuthView.as_view(), name='google_auth_callback'),
]

