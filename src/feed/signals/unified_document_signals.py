import logging

from django.db.models.signals import pre_save
from django.dispatch import receiver

from feed.tasks import delete_feed_entry
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)

"""
Signal handlers for ResearchhubUnifiedDocument model.

The signal handlers are responsible for cleaning up feed entries
when unified documents are removed.
"""

logger = logging.getLogger(__name__)


@receiver(
    pre_save,
    sender=ResearchhubUnifiedDocument,
    dispatch_uid="unified_document_removed",
)
def handle_unified_document_removed(sender, instance, **kwargs):
    """
    When a unified document is marked as removed, delete all related feed entries.
    """
    try:
        # Get the original instance to check if is_removed changed
        if instance.id:
            original = ResearchhubUnifiedDocument.objects.get(id=instance.id)
            # If document is being removed, delete all feed entries
            if not original.is_removed and instance.is_removed:
                delete_feed_entries_for_unified_document(instance)
    except Exception as e:
        logger.error(f"Failed to handle unified document removal: {e}")


def delete_feed_entries_for_unified_document(unified_document):
    """
    Delete all feed entries associated with the unified document.
    This includes entries where the unified document is either:
    1. The item itself
    2. The parent item
    """
    # Get all feed entries directly linked to this unified document
    feed_entries = unified_document.feed_entries.all()

    for entry in feed_entries:
        # Delete each feed entry
        try:
            delete_feed_entry.apply_async(
                args=(
                    entry.object_id,
                    entry.content_type_id,
                ),
                priority=1,
            )
        except Exception as e:
            logger.error(f"Failed to delete feed entry {entry.id}: {e}")
