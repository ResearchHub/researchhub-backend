from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("user", "0150_author_user_soft_delete_fields")]

    operations = [
        migrations.AlterField(
            model_name="gatekeeper",
            name="type",
            field=models.CharField(
                choices=[
                    ("EDITOR_PAYOUT_ADMIN", "EDITOR_PAYOUT_ADMIN"),
                    ("ELN", "ELN"),
                    ("CLIENT_PERMISSIONS", "CLIENT_PERMISSIONS"),
                    ("PAYOUT_EXCLUSION", "PAYOUT_EXCLUSION"),
                    ("PERMISSIONS_DASH", "PERMISSIONS_DASH"),
                    ("RESEARCH_AI_UNLIMITED", "RESEARCH_AI_UNLIMITED"),
                ],
                db_index=True,
                max_length=128,
            ),
        ),
    ]
