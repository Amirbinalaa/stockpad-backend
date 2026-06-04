from django.conf import settings
from django.db import models


class UserPreference(models.Model):
    UNIT_KG = "kg"
    UNIT_LITER = "L"
    UNIT_PCS = "pcs"

    DATE_DMY = "DD/MM/YYYY"
    DATE_MDY = "MM/DD/YYYY"

    THEME_LIGHT = "light"
    THEME_DARK = "dark"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    default_unit = models.CharField(
        max_length=10,
        choices=[
            (UNIT_KG, "kg"),
            (UNIT_LITER, "L"),
            (UNIT_PCS, "pcs"),
        ],
        default=UNIT_KG,
    )
    date_format = models.CharField(
        max_length=20,
        choices=[
            (DATE_DMY, "DD/MM/YYYY"),
            (DATE_MDY, "MM/DD/YYYY"),
        ],
        default=DATE_DMY,
    )
    theme = models.CharField(
        max_length=10,
        choices=[
            (THEME_LIGHT, "light"),
            (THEME_DARK, "dark"),
        ],
        default=THEME_LIGHT,
    )
    dead_stock_threshold_days = models.IntegerField(default=30)


