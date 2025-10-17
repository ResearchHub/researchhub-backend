# Performance optimization: Add composite indexes for fundraise queries
# This dramatically speeds up the funding feed view by optimizing the
# Exists subquery that checks for active fundraises

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("purchase", "0037_purchase_purchase_usr_status_type_idx"),
        ("researchhub_document", "0067_researchhubpost_image"),
    ]

    operations = [
        # Composite index for the Exists subquery in funding_feed_view
        # This index covers: unified_document_id (FK), status (WHERE), end_date (WHERE)
        migrations.AddIndex(
            model_name="fundraise",
            index=models.Index(
                fields=["unified_document_id", "status", "end_date"],
                name="fundraise_unidoc_status_end_idx",
            ),
        ),
    ]

