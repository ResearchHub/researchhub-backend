from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "researchhub_document",
            "0078_remove_researchjourney_journal_fields",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="researchhubpost",
            name="preview_img",
            field=models.URLField(
                blank=True,
                default=None,
                max_length=2048,
                null=True,
            ),
        ),
    ]
