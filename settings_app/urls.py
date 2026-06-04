from django.urls import path

from .views import AccountView, UserPreferenceView


app_name = "settings_app"

urlpatterns = [
    path("account/", AccountView.as_view(), name="account"),
    path("preferences/", UserPreferenceView.as_view(), name="preferences"),
]

