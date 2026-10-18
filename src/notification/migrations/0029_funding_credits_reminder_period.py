from django.contrib.postgres.fields.hstore import KeyTransform
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notification", "0028_alter_notification_notification_type"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="notification",
            constraint=models.UniqueConstraint(
                models.F("recipient"),
                KeyTransform("reminder_period", "extra"),
                condition=models.Q(notification_type="FUNDING_CREDITS_REMINDER"),
                name="uniq_funding_reminder_period",
            ),
        ),
    ]
