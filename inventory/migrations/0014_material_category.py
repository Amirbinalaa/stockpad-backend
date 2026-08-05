from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0013_alter_material_reorder_point"),
    ]

    operations = [
        migrations.AddField(
            model_name="material",
            name="category",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional explicit category; leave blank to auto-infer from material name.",
                max_length=64,
            ),
        ),
    ]
