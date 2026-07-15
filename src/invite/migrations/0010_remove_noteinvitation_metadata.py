from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("invite", "0009_noteinvitation_metadata_and_email_length"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="noteinvitation",
            name="metadata",
        ),
    ]
