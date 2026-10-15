"""Move existing changelog posts from DISCUSSION to CHANGELOG.

Before the CHANGELOG type existed, changelogs were DISCUSSION posts whose IDs
the frontend hard-coded, and the notebook created changelog drafts as
DISCUSSION notes once it shipped. Only moderators could create those, and no
other notebook flow creates DISCUSSION notes since then. Both are retyped
here, along with each post's unified document and note. Their feed entries
are dropped because changelogs are no longer shown in feeds.
"""

from datetime import UTC, datetime

from django.db import migrations
from django.db.models import Q

CHANGELOG = "CHANGELOG"
DISCUSSION = "DISCUSSION"

# Production post IDs from the frontend's former `CHANGELOG_POST_IDS`.
LEGACY_CHANGELOG_POST_IDS = [
    32976,
    32975,
    32974,
    32973,
    32972,
    32971,
    32970,
    32969,
    32728,
    32727,
    32729,
    32726,
    32725,
    32502,
    32356,
    32355,
    32354,
    32306,
    32298,
    32266,
    32263,
    32262,
    32261,
    32260,
    32259,
    32258,
    32256,
    32257,
    32255,
    17886,
    17884,
    17874,
    17859,
    17850,
    17846,
    17841,
    17839,
    17833,
    4594,
]

# The frontend's former `CHANGELOG_NOTEBOOK_ROLLOUT_AT`.
NOTEBOOK_CHANGELOG_ROLLOUT_AT = datetime(2026, 8, 10, 20, 56, 32, tzinfo=UTC)


def mark_changelogs(apps, schema_editor):
    FeedEntry = apps.get_model("feed", "FeedEntry")
    Note = apps.get_model("note", "Note")
    ResearchhubPost = apps.get_model("researchhub_document", "ResearchhubPost")
    ResearchhubUnifiedDocument = apps.get_model(
        "researchhub_document", "ResearchhubUnifiedDocument"
    )

    notebook_changelog_note_ids = set(
        Note.objects.filter(
            created_by__moderator=True,
            document_type=DISCUSSION,
            created_date__gte=NOTEBOOK_CHANGELOG_ROLLOUT_AT,
        ).values_list("id", flat=True)
    )
    posts = ResearchhubPost.objects.filter(
        Q(id__in=LEGACY_CHANGELOG_POST_IDS) | Q(note_id__in=notebook_changelog_note_ids),
        document_type=DISCUSSION,
    )
    post_rows = list(posts.values_list("id", "unified_document_id", "note_id"))
    post_ids = [post_id for post_id, _, _ in post_rows]
    unified_document_ids = [doc_id for _, doc_id, _ in post_rows if doc_id]
    note_ids = notebook_changelog_note_ids | {
        note_id for _, _, note_id in post_rows if note_id
    }

    ResearchhubPost.objects.filter(id__in=post_ids).update(document_type=CHANGELOG)
    ResearchhubUnifiedDocument.objects.filter(id__in=unified_document_ids).update(
        document_type=CHANGELOG
    )
    Note.objects.filter(id__in=note_ids).update(document_type=CHANGELOG)
    FeedEntry.objects.filter(unified_document_id__in=unified_document_ids).delete()


def unmark_changelogs(apps, schema_editor):
    """Restore DISCUSSION. Deleted feed entries are not recreated."""
    Note = apps.get_model("note", "Note")
    ResearchhubPost = apps.get_model("researchhub_document", "ResearchhubPost")
    ResearchhubUnifiedDocument = apps.get_model(
        "researchhub_document", "ResearchhubUnifiedDocument"
    )

    ResearchhubPost.objects.filter(document_type=CHANGELOG).update(
        document_type=DISCUSSION
    )
    ResearchhubUnifiedDocument.objects.filter(document_type=CHANGELOG).update(
        document_type=DISCUSSION
    )
    Note.objects.filter(document_type=CHANGELOG).update(document_type=DISCUSSION)


class Migration(migrations.Migration):
    dependencies = [
        ("feed", "0039_hiddenfeedentry"),
        ("note", "0014_note_document_type_changelog"),
        ("researchhub_document", "0083_document_type_changelog"),
    ]

    operations = [
        migrations.RunPython(mark_changelogs, unmark_changelogs),
    ]
