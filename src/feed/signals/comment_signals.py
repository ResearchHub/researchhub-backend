import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from feed.models import FeedEntry
from feed.tasks import (
    create_feed_entry,
    delete_feed_entry,
    refresh_feed_entries_for_objects,
)
from researchhub_comment.related_models.rh_comment_model import RhCommentModel

"""
Signal handlers for Comment model.

The signal handlers are responsbile for creating, refreshing, and deleting feed
entries when comments are created, edited, and removed, respectively.
"""

logger = logging.getLogger(__name__)


@receiver(post_save, sender=RhCommentModel)
def handle_comment_saved(sender, instance, created, **kwargs):
    """
    When a comment is created, edited, or removed, create, refresh, or delete
    its feed entries.
    """
    comment = instance

    try:
        if created:
            _create_comment_feed_entries(comment)
        elif comment.is_removed:
            _delete_comment_feed_entries(comment)
        else:
            _refresh_comment_feed_entries(comment)

        _update_metrics(comment)
    except Exception as e:
        action = "create" if created else "update"
        logger.error(f"Failed to {action} feed entry for comment {comment.id}: {e}")


def _update_metrics(comment):
    if not getattr(comment, "unified_document", None):
        return

    # Update the metrics (number of replies) for the associated documents
    document = comment.unified_document.get_document()  # can be paper or post
    document_content_type = ContentType.objects.get_for_model(document)

    refresh_feed_entries_for_objects.apply_async(
        args=(document.id, document_content_type.id),
        priority=1,
    )


def _create_comment_feed_entries(comment):
    if not getattr(comment, "unified_document", None) or not hasattr(
        comment.unified_document, "hubs"
    ):
        return

    hub_ids = list(comment.unified_document.hubs.values_list("id", flat=True))
    transaction.on_commit(
        lambda: create_feed_entry.apply_async(
            args=(
                comment.id,
                ContentType.objects.get_for_model(comment).id,
                FeedEntry.PUBLISH,
                hub_ids,
                comment.created_by.id,
            ),
            priority=1,
        )
    )


def _refresh_comment_feed_entries(comment: RhCommentModel) -> None:
    """Re-serialize the comment's feed entries so edits reach the feed."""
    comment_content_type_id = ContentType.objects.get_for_model(comment).id
    transaction.on_commit(
        lambda: refresh_feed_entries_for_objects.apply_async(
            args=(comment.id, comment_content_type_id),
            priority=1,
        )
    )


def _delete_comment_feed_entries(comment):
    if not getattr(comment, "unified_document", None) or not hasattr(
        comment.unified_document, "hubs"
    ):
        return

    hub_ids = list(comment.unified_document.hubs.values_list("id", flat=True))
    transaction.on_commit(
        lambda: delete_feed_entry.apply_async(
            args=(
                comment.id,
                ContentType.objects.get_for_model(comment).id,
                hub_ids,
            ),
            priority=1,
        )
    )
