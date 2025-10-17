# Performance optimization: Add composite index for post queries
# This speeds up the funding feed view by optimizing the document_type filter

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("researchhub_document", "0068_alter_researchhubpost_document_type_and_more"),
    ]

    operations = [
        # Composite index for filtering posts by document_type and related unified_document
        migrations.AddIndex(
            model_name="researchhubpost",
            index=models.Index(
                fields=["document_type", "unified_document_id"],
                name="post_doctype_unidoc_idx",
            ),
        ),
    ]

