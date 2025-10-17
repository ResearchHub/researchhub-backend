# Performance optimization: Add composite indexes for grant queries
# This dramatically speeds up the grant feed view by optimizing the
# Exists subquery that checks for active grants

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("purchase", "0038_add_fundraise_composite_indexes"),
        ("researchhub_document", "0069_add_post_composite_indexes"),
    ]

    operations = [
        # Composite index for the Exists subquery in grant_feed_view
        # This index covers: unified_document_id (FK), status (WHERE), end_date (WHERE)
        migrations.AddIndex(
            model_name="grant",
            index=models.Index(
                fields=["unified_document_id", "status", "end_date"],
                name="grant_unidoc_status_end_idx",
            ),
        ),
    ]

