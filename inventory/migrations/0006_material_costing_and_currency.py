from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0005_materialrequest"),
    ]

    operations = [
        migrations.AddField(
            model_name="material",
            name="cost_price",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="material",
            name="currency",
            field=models.CharField(
                choices=[
                    ("EGP", "EGP"),
                    ("USD", "USD"),
                    ("EUR", "EUR"),
                    ("SAR", "SAR"),
                    ("AED", "AED"),
                ],
                default="EGP",
                max_length=3,
            ),
        ),
        migrations.AddField(
            model_name="material",
            name="costing_method",
            field=models.CharField(
                choices=[
                    ("MOVING_AVG", "Moving Average Cost"),
                    ("FIFO", "First-In, First-Out"),
                ],
                default="MOVING_AVG",
                max_length=12,
            ),
        ),
    ]
