import logging
from functools import partial

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from feed.models import FeedEntry
from feed.serializers import serialize_feed_metrics
from feed.tasks import create_feed_entry, delete_feed_entry, update_feed_metrics
from researchhub_comment.related_models.rh_comment_model import RhCommentModel

"""
Signal handlers for Comment model.

The signal handlers are responsbile for creating and deleting feed entries
when comments are created and removed, respectively.
"""

logger = logging.getLogger(__name__)


@receiver(post_save, sender=RhCommentModel)
def handle_comment_created_or_removed(sender, instance, created, **kwargs):
    """
    When a comment is created or removed, create or delete a feed entry.
    """
    comment = instance

    try:
        if created:
            _create_comment_feed_entries(comment)
        elif comment.is_removed:
            _delete_comment_feed_entries(comment)

        _update_metrics(comment)
    except Exception as e:
        action = "create" if created else "delete"
        logger.error(f"Failed to {action} feed entry for comment {comment.id}: {e}")


def _update_metrics(comment):
    if not getattr(comment, "unified_document", None):
        return

    # Update the metrics (number of replies) for the associated documents
    document = comment.unified_document.get_document()  # can be paper or post
    content_type = ContentType.objects.get_for_model(document)
    metrics = serialize_feed_metrics(document, content_type)

    update_feed_metrics.apply_async(
        args=(
            document.id,
            ContentType.objects.get_for_model(document).id,
            metrics,
        ),
        priority=1,
    )

    parent_comment = comment.parent
    if parent_comment:
        # Update the metrics for the parent comment feed entry
        parent_comment_content_type = ContentType.objects.get_for_model(parent_comment)
        metrics = serialize_feed_metrics(parent_comment, parent_comment_content_type)
        update_feed_metrics.apply_async(
            args=(
                parent_comment.id,
                ContentType.objects.get_for_model(parent_comment).id,
                metrics,
            ),
            priority=1,
        )


def _create_comment_feed_entries(comment):
    # Validate that the comment is associated with a unified document with hubs
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


def _delete_comment_feed_entries(comment):
    # Validate that the comment is associated with a unified document with hubs
    if not getattr(comment, "unified_document", None) or not hasattr(
        comment.unified_document, "hubs"
    ):
        return

    hub_ids = list(comment.unified_document.hubs.values_list("id", flat=True))
    tasks = [
        partial(
            delete_feed_entry.apply_async,
            args=(
                comment.id,
                ContentType.objects.get_for_model(comment).id,
                hub_ids,
            ),
            priority=1,
        )
        for hub in comment.unified_document.hubs.all()
    ]
    transaction.on_commit(lambda: [task() for task in tasks])
