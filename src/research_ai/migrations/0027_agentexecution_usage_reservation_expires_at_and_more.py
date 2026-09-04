from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("research_ai", "0026_llmusageevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentexecution",
            name="usage_reservation_expires_at",
            field=models.DateTimeField(
                blank=True,
                db_comment=(
                    "Renewable lease reserving the user's Research AI budget slot "
                    "while this execution may still be producing spend."
                ),
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="proposaldraft",
            name="usage_reservation_expires_at",
            field=models.DateTimeField(
                blank=True,
                db_comment=(
                    "Renewable lease reserving the creator's Research AI budget slot "
                    "while this draft may still be producing spend."
                ),
                null=True,
            ),
        ),
    ]
