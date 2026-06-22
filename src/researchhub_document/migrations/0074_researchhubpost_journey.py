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
        migrations.AddConstraint(
            model_name="researchhubpost",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    document_type="REGISTERED_REPORT",
                    journey__isnull=False,
                ),
                fields=("journey",),
                name="unique_rr_per_journey",
            ),
        ),
    ]
