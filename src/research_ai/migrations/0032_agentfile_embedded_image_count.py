from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("research_ai", "0031_llmusageevent_tier"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentfile",
            name="embedded_image_count",
            field=models.PositiveIntegerField(
                blank=True,
                db_comment="Images kept from a Word document and stored beside it; null for other formats and files processed before this was recorded.",
                null=True,
            ),
        ),
    ]
