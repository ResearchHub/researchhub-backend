from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("researchhub_document", "0085_remove_researchhubpost_eln_src"),
    ]

    operations = [
        migrations.AddField(
            model_name="researchhubpost",
            name="external_source_id",
            field=models.CharField(
                max_length=128,
                null=True,
                blank=True,
                unique=True,
                help_text="Namespaced source key for rerunnable imports; never derived from title.",
            ),
        ),
    ]
