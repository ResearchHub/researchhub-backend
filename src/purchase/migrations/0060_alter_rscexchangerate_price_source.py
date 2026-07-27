from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("purchase", "0059_enforce_balance_lock_state"),
    ]

    operations = [
        migrations.AlterField(
            model_name="rscexchangerate",
            name="price_source",
            field=models.CharField(
                choices=[
                    ("COIN_GECKO", "COIN_GECKO"),
                ],
                default="COIN_GECKO",
                help_text="API used to get the price",
                max_length=255,
                null=True,
            ),
        ),
    ]
