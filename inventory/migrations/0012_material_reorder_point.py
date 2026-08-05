from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0011_add_product_and_productmaterial'),
    ]

    operations = [
        migrations.AddField(
            model_name='material',
            name='reorder_point',
            field=models.DecimalField(
                decimal_places=2,
                default=0.0,
                help_text='Safety stock threshold',
                max_digits=10,
            ),
        ),
    ]
