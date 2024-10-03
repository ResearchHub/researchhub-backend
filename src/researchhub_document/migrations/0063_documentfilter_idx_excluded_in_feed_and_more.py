# Generated by Django 4.2.15 on 2024-10-01 19:56

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "researchhub_document",
            "0062_alter_researchhubunifieddocumenthub_unique_together_and_more",
        ),
    ]

    operations = [
        migrations.AddIndex(
            model_name="documentfilter",
            index=models.Index(
                fields=["is_excluded_in_feed"], name="idx_excluded_in_feed"
            ),
        ),
        migrations.AddIndex(
            model_name="researchhubunifieddocument",
            index=models.Index(
                condition=models.Q(("document_type", "PAPER")),
                fields=[
                    "is_removed",
                    "document_type",
                    "hot_score_v2",
                    "document_filter",
                ],
                name="idx_paper_filter_sort",
            ),
        ),
    ]