from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        (
            "researchhub_document",
            "0077_remove_researchhubunifieddocument_doc_type_hot_score_idx_and_more",
        ),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="researchjourney",
            name="journey_journal_idx",
        ),
        migrations.RemoveField(
            model_name="researchjourney",
            name="is_in_journal",
        ),
        migrations.RemoveField(
            model_name="researchjourney",
            name="journal_included_date",
        ),
    ]
