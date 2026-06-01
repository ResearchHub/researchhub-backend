import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0145_riskscore_transfer"),
    ]

    operations = [
        migrations.AddField(
            model_name="riskscoreevent",
            name="action_date",
            field=models.DateTimeField(default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.RemoveIndex(
            model_name="riskscoreevent",
            name="risk_event_user_date_idx",
        ),
        migrations.AddIndex(
            model_name="riskscoreevent",
            index=models.Index(
                fields=["user", "action_date"], name="risk_event_user_action_idx"
            ),
        ),
        migrations.AlterModelOptions(
            name="riskscoreevent",
            options={"ordering": ["-action_date"]},
        ),
    ]
