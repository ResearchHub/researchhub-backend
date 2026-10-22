from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0154_user_complete_profile_email_sent_date"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userverification",
            name="verified_by",
            field=models.TextField(
                choices=[("MANUAL", "Manual"), ("PERSONA", "Persona"), ("X", "X")]
            ),
        ),
    ]
