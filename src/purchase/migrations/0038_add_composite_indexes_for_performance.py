# Generated manually for performance optimization

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("purchase", "0037_purchase_purchase_usr_status_type_idx"),
    ]

    operations = [
        # Grant model composite indexes
        migrations.AddIndex(
            model_name="grant",
            index=models.Index(
                fields=["unified_document", "status"],
                name="grant_unified_doc_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="grant",
            index=models.Index(
                fields=["unified_document", "status", "end_date"],
                name="grant_unified_doc_status_end_idx",
            ),
        ),
        # Fundraise model composite indexes
        migrations.AddIndex(
            model_name="fundraise",
            index=models.Index(
                fields=["unified_document", "status"],
                name="fundraise_unified_doc_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="fundraise",
            index=models.Index(
                fields=["unified_document", "status", "end_date"],
                name="fundraise_unified_doc_status_end_idx",
            ),
        ),
    ]

