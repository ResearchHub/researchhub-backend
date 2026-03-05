import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("purchase", "0048_wallet_circle_base_wallet_id"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="grant",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending"),
                    ("OPEN", "Open"),
                    ("CLOSED", "Closed"),
                    ("COMPLETED", "Completed"),
                    ("DECLINED", "Declined"),
                ],
                default="PENDING",
                help_text="Current status of the grant",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="grant",
            name="reviewed_by",
            field=models.ForeignKey(
                blank=True,
                help_text="Moderator who approved or declined this grant",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="reviewed_grants",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="grant",
            name="reviewed_date",
            field=models.DateTimeField(
                blank=True,
                help_text="When the moderation decision was made",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="grant",
            name="decline_reason",
            field=models.TextField(
                blank=True,
                help_text="Reason provided by moderator for declining the grant",
                null=True,
            ),
        ),
    ]
