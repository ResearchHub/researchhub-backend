import django.contrib.postgres.fields
from django.db import migrations, models


def copy_channel_to_channels(apps, schema_editor):
    GeneratedEmail = apps.get_model("research_ai", "GeneratedEmail")
    for row in GeneratedEmail.objects.exclude(channel="").iterator():
        GeneratedEmail.objects.filter(pk=row.pk).update(channels=[row.channel])


class Migration(migrations.Migration):
    dependencies = [
        ("research_ai", "0021_agentcontextmessage_provider_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="generatedemail",
            name="channels",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(
                    choices=[
                        ("email", "Email"),
                        ("linkedin", "LinkedIn"),
                        ("x", "X"),
                    ],
                    max_length=16,
                ),
                blank=True,
                db_comment=(
                    "Outreach channels when marked sent "
                    "(email / linkedin / x). Empty until sent."
                ),
                default=list,
                size=None,
            ),
        ),
        migrations.RunPython(
            copy_channel_to_channels,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="generatedemail",
            name="channel",
        ),
        migrations.RemoveField(
            model_name="generatedemail",
            name="notes",
        ),
    ]
