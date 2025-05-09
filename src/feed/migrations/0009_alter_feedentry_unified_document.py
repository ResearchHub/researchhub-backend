# Generated by Django 5.1.5 on 2025-03-05 11:30

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feed", "0008_feedentry_unified_document"),
        (
            "researchhub_document",
            "0066_remove_researchhubunifieddocument_idx_unified_doc_hot_score_v2_and_more",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="feedentry",
            name="unified_document",
            field=models.ForeignKey(
                db_comment="The unified document associated with the feed entry. Directly added to the feed entry for performance reasons.",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="feed_entries",
                to="researchhub_document.researchhubunifieddocument",
            ),
        ),
    ]
