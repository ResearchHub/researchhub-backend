"""Move existing changelog posts from DISCUSSION to CHANGELOG.

Before the CHANGELOG type existed, changelogs were DISCUSSION posts whose IDs
the frontend hard-coded. Exactly those posts are retyped, along with their
unified documents and notes, and their feed entries are dropped because
changelogs are no longer shown in feeds.

The IDs are production IDs, so other environments are left untouched.
"""

from django.conf import settings
from django.db import migrations

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


def retype_listed_posts(apps, from_type, to_type):
    """Retype the listed posts, their unified documents and their notes.

    Returns the IDs of the unified documents that were retyped.
    """
    Note = apps.get_model("note", "Note")
    ResearchhubPost = apps.get_model("researchhub_document", "ResearchhubPost")
    ResearchhubUnifiedDocument = apps.get_model(
        "researchhub_document", "ResearchhubUnifiedDocument"
    )

    posts = ResearchhubPost.objects.filter(
        id__in=LEGACY_CHANGELOG_POST_IDS,
        document_type=from_type,
    )
    post_rows = list(posts.values_list("id", "unified_document_id", "note_id"))
    post_ids = [post_id for post_id, _, _ in post_rows]
    unified_document_ids = [doc_id for _, doc_id, _ in post_rows if doc_id]
    note_ids = [note_id for _, _, note_id in post_rows if note_id]

    ResearchhubPost.objects.filter(id__in=post_ids).update(document_type=to_type)
    ResearchhubUnifiedDocument.objects.filter(id__in=unified_document_ids).update(
        document_type=to_type
    )
    Note.objects.filter(id__in=note_ids).update(document_type=to_type)
    return unified_document_ids


def mark_changelogs(apps, schema_editor):
    if not settings.PRODUCTION:
        return

    FeedEntry = apps.get_model("feed", "FeedEntry")
    unified_document_ids = retype_listed_posts(apps, DISCUSSION, CHANGELOG)
    FeedEntry.objects.filter(unified_document_id__in=unified_document_ids).delete()


def unmark_changelogs(apps, schema_editor):
    """Restore DISCUSSION on the listed posts only.

    Changelogs created after this migration keep their type, and deleted feed
    entries are not recreated.
    """
    if not settings.PRODUCTION:
        return

    retype_listed_posts(apps, CHANGELOG, DISCUSSION)


class Migration(migrations.Migration):
    dependencies = [
        ("feed", "0039_hiddenfeedentry"),
        ("note", "0014_note_document_type_changelog"),
        ("researchhub_document", "0083_document_type_changelog"),
    ]

    operations = [
        migrations.RunPython(mark_changelogs, unmark_changelogs),
    ]
