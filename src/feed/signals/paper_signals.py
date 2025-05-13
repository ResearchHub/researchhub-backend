import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import m2m_changed, pre_save
from django.dispatch import receiver

from feed.models import FeedEntry
from feed.tasks import create_feed_entry, delete_feed_entry
from hub.models import Hub
from paper.related_models.paper_model import Paper
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)

"""
Signal handlers for Paper model.

The signal handlers are responsible for creating and deleting feed entries
when papers are added to or removed from hubs.
"""

logger = logging.getLogger(__name__)


@receiver(
    m2m_changed,
    sender=ResearchhubUnifiedDocument.hubs.through,
    dispatch_uid="unified_doc_hubs_changed",
)
def handle_unified_doc_hubs_changed(sender, instance, action, pk_set, **kwargs):
    try:
        if action == "post_add":
            _create_paper_feed_entries(instance, pk_set)
        elif action == "post_remove":
            _delete_paper_feed_entries(instance, pk_set)
    except Exception as e:
        action = "create" if action == "post_add" else "delete"
        logger.error(
            f"Failed to {action} feed entries for unified doc hubs changed: {e}"
        )


@receiver(
    pre_save,
    sender=Paper,
    dispatch_uid="paper_removed",
)
def handle_paper_removed(sender, instance, **kwargs):
    """
    When a paper is marked as removed, delete all related feed entries.
    """
    try:
        # Get the original instance to check if is_removed changed
        if instance.id:
            original = Paper.objects.get(id=instance.id)
            # If paper is being removed, delete all feed entries
            if not original.is_removed and instance.is_removed:
                delete_feed_entries_for_paper(instance)
    except Exception as e:
        logger.error(f"Failed to handle paper removal: {e}")


def delete_feed_entries_for_paper(paper):
    """
    Delete all feed entries associated with the paper.
    """
    try:
        # Get the content type for Paper model
        paper_content_type = ContentType.objects.get_for_model(paper)

        # Get all feed entries for this paper
        feed_entries = FeedEntry.objects.filter(
            content_type=paper_content_type, object_id=paper.id
        )

        # Delete each feed entry with its specific parent information
        for entry in feed_entries:
            delete_feed_entry.apply_async(
                args=(
                    paper.id,
                    paper_content_type.id,
                    entry.parent_object_id,
                    entry.parent_content_type_id,
                ),
                priority=1,
            )

        logger.info(f"Deleted feed entries for paper {paper.id}: {paper.title}")
    except Exception as e:
        logger.error(f"Failed to delete feed entries for paper {paper.id}: {e}")


def _create_paper_feed_entries(instance, pk_set):
    """
    Create feed entries when papers are added to hubs.
    """
    for entity_id in pk_set:
        if (
            isinstance(instance, ResearchhubUnifiedDocument)
            and instance.document_type == "PAPER"
        ):
            hub = instance.hubs.get(id=entity_id)
            paper = instance.paper
        elif isinstance(instance, Hub):  # instance is Hub
            hub = instance
            paper = hub.related_documents.get(id=entity_id).paper
        else:
            continue

        # We order feed entries by publish date, so we don't need to
        # create feed entries for papers that don't have a publish date
        if paper.paper_publish_date is None:
            continue

        create_feed_entry.apply_async(
            args=(
                paper.id,
                ContentType.objects.get_for_model(paper).id,
                "PUBLISH",
                hub.id,
                ContentType.objects.get_for_model(hub).id,
            ),
            priority=1,
        )


def _delete_paper_feed_entries(instance, pk_set):
    """
    Delete feed entries when papers are removed from hubs.
    """
    for entity_id in pk_set:
        if (
            isinstance(instance, ResearchhubUnifiedDocument)
            and instance.document_type == "PAPER"
        ):
            hub = Hub.objects.get(id=entity_id)
            paper = instance.paper
        elif isinstance(instance, Hub):  # instance is Hub
            hub = instance
            paper = hub.related_documents.get(id=entity_id).paper
        else:
            continue

        delete_feed_entry.apply_async(
            args=(
                paper.id,
                ContentType.objects.get_for_model(paper).id,
                hub.id,
                ContentType.objects.get_for_model(hub).id,
            ),
            priority=1,
        )
