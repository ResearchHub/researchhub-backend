from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("researchhub_document", "0068_alter_researchhubpost_document_type_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="researchhubpost",
            index=models.Index(
                fields=["document_type", "unified_document_id"],
                name="post_doctype_idx",
            ),
        ),
    ]

