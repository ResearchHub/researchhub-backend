# Generated manually for USD balance and contributions

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("purchase", "0037_purchase_purchase_usr_status_type_idx"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Create UsdBalance model
        migrations.CreateModel(
            name="UsdBalance",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_date", models.DateTimeField(auto_now_add=True)),
                ("updated_date", models.DateTimeField(auto_now=True)),
                (
                    "amount_cents",
                    models.IntegerField(
                        help_text="Amount in cents. Positive = credit, negative = debit"
                    ),
                ),
                ("object_id", models.PositiveIntegerField(blank=True, null=True)),
                ("description", models.CharField(blank=True, max_length=255)),
                (
                    "content_type",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="contenttypes.contenttype",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="usd_balances",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        # Create UsdFundraiseContribution model
        migrations.CreateModel(
            name="UsdFundraiseContribution",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_date", models.DateTimeField(auto_now_add=True)),
                ("updated_date", models.DateTimeField(auto_now=True)),
                (
                    "amount_cents",
                    models.IntegerField(help_text="Contribution amount in cents"),
                ),
                (
                    "fee_cents",
                    models.IntegerField(default=0, help_text="9% fee in cents"),
                ),
                (
                    "fundraise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="usd_contributions",
                        to="purchase.fundraise",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="usd_fundraise_contributions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        # Add usd_amount_raised_cents to Fundraise
        migrations.AddField(
            model_name="fundraise",
            name="usd_amount_raised_cents",
            field=models.IntegerField(
                default=0, help_text="Total USD raised in cents"
            ),
        ),
        # Add indexes for UsdBalance
        migrations.AddIndex(
            model_name="usdbalance",
            index=models.Index(fields=["user"], name="purchase_us_user_id_a1b2c3_idx"),
        ),
        migrations.AddIndex(
            model_name="usdbalance",
            index=models.Index(
                fields=["created_date"], name="purchase_us_created_d4e5f6_idx"
            ),
        ),
        # Add indexes for UsdFundraiseContribution
        migrations.AddIndex(
            model_name="usdfundraisecontribution",
            index=models.Index(
                fields=["fundraise"], name="purchase_us_fundrai_g7h8i9_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="usdfundraisecontribution",
            index=models.Index(fields=["user"], name="purchase_us_user_id_j0k1l2_idx"),
        ),
    ]
