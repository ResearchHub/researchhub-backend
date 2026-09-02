from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("research_ai", "0026_llmusageevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentexecution",
            name="usage_reservation_active",
            field=models.BooleanField(
                db_comment=(
                    "Whether this execution still reserves its user's Research AI "
                    "budget slot, including while a cancelled provider call unwinds."
                ),
                default=False,
            ),
        ),
        migrations.AddField(
            model_name="proposaldraft",
            name="usage_reservation_active",
            field=models.BooleanField(
                db_comment=(
                    "Whether this draft still reserves its creator's Research AI "
                    "budget slot, including while cancelled work unwinds."
                ),
                default=False,
            ),
        ),
    ]
