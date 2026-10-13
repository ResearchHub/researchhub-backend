from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("research_ai", "0032_outreachmailbox_generatedemail_external_lead_id_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="generatedemail",
            name="complained_at",
        ),
        migrations.RemoveField(
            model_name="generatedemail",
            name="ses_message_id",
        ),
    ]
