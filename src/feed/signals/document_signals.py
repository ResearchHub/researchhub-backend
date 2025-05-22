import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import m2m_changed
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
        instance.document_type == "PAPER" or instance.document_type == "DISCUSSION"
    ):
        hub_ids = list(pk_set)
        item = instance.get_document()

        create_feed_entry.apply_async(
            args=(
                item.id,
                ContentType.objects.get_for_model(item).id,
                "PUBLISH",
                hub_ids,
            ),
            priority=1,
        )
    elif isinstance(instance, Hub):  # instance is Hub
        hub = instance
        for document_id in pk_set:
            unified_document = hub.related_documents.get(id=document_id)
            item = unified_document.get_document()
            hub_ids = list(item.hubs.values_list("id", flat=True))
            create_feed_entry.apply_async(
                args=(
                    item.id,
                    ContentType.objects.get_for_model(item).id,
                    "PUBLISH",
                    hub_ids,
                ),
                priority=1,
            )


def _delete_document_feed_entries(instance, pk_set):
    """
    Delete feed entries when documents are removed from hubs.
    """
    if isinstance(instance, ResearchhubUnifiedDocument) and (
        instance.document_type == "PAPER" or instance.document_type == "DISCUSSION"
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
