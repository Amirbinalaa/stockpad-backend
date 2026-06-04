from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        MANAGER = "manager", "Manager"
        OPERATOR = "operator", "Operator"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.ADMIN,
    )
    profile_picture = models.ImageField(
        upload_to="profile_pics/",
        null=True,
        blank=True,
    )

