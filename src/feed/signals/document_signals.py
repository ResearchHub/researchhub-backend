import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import m2m_changed, pre_save
from django.dispatch import receiver

from feed.tasks import create_feed_entry, delete_feed_entry
from hub.models import Hub
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)

"""
Signal handlers for unified document model.

The signal handlers are responsible for creating and deleting feed entries
when documents are added to or removed from hubs.
"""

logger = logging.getLogger(__name__)


@receiver(
    m2m_changed,
    sender=ResearchhubUnifiedDocument.hubs.through,
    dispatch_uid="unified_doc_hubs_changed",
)
def handle_document_hubs_changed(sender, instance, action, pk_set, **kwargs):
    try:
        if action == "post_add":
            _create_document_feed_entries(instance, pk_set)
        elif action == "post_remove":
            _delete_document_feed_entries(instance, pk_set)
    except Exception as e:
        action = "create" if action == "post_add" else "delete"
        logger.error(
            f"Failed to {action} feed entries for unified doc hubs changed: {e}"
        )


def _create_document_feed_entries(instance, pk_set):
    """
    Create feed entries when documents are added to hubs.
    """
    if isinstance(instance, ResearchhubUnifiedDocument) and (
        hasattr(instance, "paper") or instance.posts.exists()
    ):
        hub_ids = list(pk_set)
        item = instance.get_document()

        # Get the user from the document
        user_id = None
        if hasattr(item, "created_by"):
            user_id = item.created_by.id
        elif hasattr(item, "uploaded_by"):
            user_id = item.uploaded_by.id

        create_feed_entry.apply_async(
            args=(
                item.id,
                ContentType.objects.get_for_model(item).id,
                "PUBLISH",
                hub_ids,
                user_id,
            ),
            priority=1,
        )
    elif isinstance(instance, Hub):  # instance is Hub
        hub = instance
        for document_id in pk_set:
            unified_document = hub.related_documents.get(id=document_id)
            item = unified_document.get_document()
            hub_ids = list(item.hubs.values_list("id", flat=True))

            # Get the user from the document
            user_id = None
            if hasattr(item, "created_by"):
                user_id = item.created_by.id
            elif hasattr(item, "uploaded_by"):
                user_id = item.uploaded_by.id

            create_feed_entry.apply_async(
                args=(
                    item.id,
                    ContentType.objects.get_for_model(item).id,
                    "PUBLISH",
                    hub_ids,
                    user_id,
                ),
                priority=1,
            )


def _delete_document_feed_entries(instance, pk_set):
    """
    Delete feed entries when documents are removed from hubs.
    """
    if isinstance(instance, ResearchhubUnifiedDocument) and (
        hasattr(instance, "paper") or instance.posts.exists()
    ):
        hub_ids = list(pk_set)
        item = instance.get_document()

        delete_feed_entry.apply_async(
            args=(
                item.id,
                ContentType.objects.get_for_model(item).id,
                hub_ids,
            ),
            priority=1,
        )
    elif isinstance(instance, Hub):  # instance is Hub
        hub = instance
        for document_id in pk_set:
            unified_document = hub.related_documents.get(id=document_id)
            item = unified_document.get_document()

            delete_feed_entry.apply_async(
                args=(
                    item.id,
                    ContentType.objects.get_for_model(item).id,
                    [hub.id],
                ),
                priority=1,
            )


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
