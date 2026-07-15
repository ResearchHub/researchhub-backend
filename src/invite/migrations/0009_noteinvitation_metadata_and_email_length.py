from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("invite", "0008_alter_noteinvitation_invite_type_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="noteinvitation",
            name="recipient_email",
            field=models.EmailField(max_length=254),
        ),
        migrations.AddField(
            model_name="noteinvitation",
            name="metadata",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Optional context for the workflow that created the invitation."
                ),
            ),
        ),
    ]
