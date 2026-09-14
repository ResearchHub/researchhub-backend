from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("research_ai", "0023_alter_proposaldraft_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentconversation",
            name="title",
            field=models.CharField(
                blank=True,
                db_comment=(
                    "User-visible conversation name. Blank until the workflow "
                    "derives one (typically from the first message) or the "
                    "user sets it."
                ),
                default="",
                max_length=255,
            ),
            preserve_default=False,
        ),
    ]
