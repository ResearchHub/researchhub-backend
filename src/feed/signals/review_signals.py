import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver

from feed.models import FeedEntry
from feed.tasks import refresh_feed_entry_by_id
from review.models.review_model import Review

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Review)
def handle_review_created_or_updated(sender, instance, created, **kwargs):
    """
    When a review is created or updated, update feed entries for:
    1. The comment that was reviewed
    2. The document associated with the unified document
    """
    review = instance

    try:
        _update_feed_entries(review)
    except Exception as e:
        action = "created" if created else "updated"
        logger.error(
            f"Failed to update feed entries for review {review.id} {action}: {e}"
        )


def _update_feed_entries(review):
    """
    Update feed entries associated with the review.
    This includes:
    - Feed entries for the document associated with the unified document
    - Feed entries for the comment that was reviewed
    """
    # Skip if review has no unified document
    if not getattr(review, "unified_document", None):
        return

    # Update feed entries for the document associated with the unified document
    document = review.unified_document.get_document()  # can be paper or post
    document_content_type = ContentType.objects.get_for_model(document)

    document_feed_entries = FeedEntry.objects.filter(
        content_type=document_content_type, object_id=document.id
    )

    for entry in document_feed_entries:
        refresh_feed_entry_by_id.apply_async(
            args=(entry.id,),
            priority=1,
        )
