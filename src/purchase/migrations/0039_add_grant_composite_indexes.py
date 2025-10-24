from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("purchase", "0038_add_fundraise_composite_indexes"),
        ("researchhub_document", "0069_add_post_composite_indexes"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="grant",
            index=models.Index(
                fields=["unified_document_id", "status", "end_date"],
                name="grant_unidoc_stat_idx",
            ),
        ),
    ]

