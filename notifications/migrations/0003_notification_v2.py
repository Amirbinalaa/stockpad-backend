import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0002_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Step 1: Wipe all existing rows so there are no integer-PK conflicts
        # when we replace the PK column type.  Notification data is ephemeral
        # and has no FK references from other tables.
        # We use a Python callable so we can choose the right SQL per DB vendor:
        #   - PostgreSQL (production) → TRUNCATE  (fast, lock-safe)
        #   - SQLite (test runner)    → DELETE FROM (TRUNCATE not supported)
        migrations.RunPython(
            code=lambda apps, schema_editor: schema_editor.execute(
                "TRUNCATE TABLE notifications_notification;"
                if schema_editor.connection.vendor == "postgresql"
                else "DELETE FROM notifications_notification;"
            ),
            reverse_code=migrations.RunPython.noop,
        ),

        # Step 2: Drop the old integer primary-key column and rebuild the table
        # with the new UUID-based schema via DeleteModel + CreateModel.  This is
        # the cleanest approach Django supports for changing a primary key type.
        migrations.DeleteModel(
            name="Notification",
        ),
        migrations.CreateModel(
            name="Notification",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        primary_key=True,
                        default=uuid.uuid4,
                        editable=False,
                        serialize=False,
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                ("message", models.TextField()),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("alert", "Alert"),
                            ("reminder", "Reminder"),
                            ("request", "Request"),
                        ],
                        default="alert",
                        max_length=10,
                    ),
                ),
                ("is_read", models.BooleanField(default=False)),
                ("group_key", models.CharField(blank=True, max_length=255, null=True)),
                ("count", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "notifications_notification",
                "ordering": ["-updated_at"],
            },
        ),
    ]
