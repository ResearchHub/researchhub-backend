from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("purchase", "0037_purchase_purchase_usr_status_type_idx"),
        ("researchhub_document", "0067_researchhubpost_image"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="fundraise",
            index=models.Index(
                fields=["unified_document_id", "status", "end_date"],
                name="fundraise_unidoc_stat_idx",
            ),
        ),
    ]

