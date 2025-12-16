import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver

from feed.serializers import serialize_feed_metrics
from feed.tasks import refresh_feed_entries_for_objects
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
        _update_metrics(comment)
    except Exception as e:
        action = "create" if created else "delete"
        logger.error(f"Failed to {action} feed entry for comment {comment.id}: {e}")


def _update_metrics(comment):
    if not getattr(comment, "unified_document", None):
        return

    # Update the metrics (number of replies) for the associated documents
    document = comment.unified_document.get_document()  # can be paper or post

    refresh_feed_entries_for_objects.apply_async(
        args=(document.id,),
        priority=1,
    )
