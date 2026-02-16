from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("purchase", "0045_remove_wallet_model"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Wallet",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("eth_address", models.CharField(max_length=255, null=True)),
                ("btc_address", models.CharField(max_length=255, null=True)),
                ("rsc_address", models.CharField(max_length=255, null=True)),
                (
                    "circle_wallet_id",
                    models.CharField(
                        blank=True, max_length=255, null=True, unique=True
                    ),
                ),
                (
                    "wallet_type",
                    models.CharField(
                        choices=[("EXTERNAL", "External"), ("CIRCLE", "Circle")],
                        default="EXTERNAL",
                        max_length=20,
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="wallet",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
