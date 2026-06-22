import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("researchhub_document", "0073_researchjourney"),
    ]

    operations = [
        migrations.AddField(
            model_name="researchhubpost",
            name="journey",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="stage_posts",
                to="researchhub_document.researchjourney",
            ),
        ),
        migrations.AddField(
            model_name="researchhubpost",
            name="message",
            field=models.TextField(
                blank=True,
                default=None,
                help_text="Version change message for registered report updates.",
                null=True,
            ),
        ),
    ]
