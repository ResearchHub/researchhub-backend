import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver

from feed.models import FeedEntry, FeedEntryLatest, FeedEntryPopular
from feed.tasks import refresh_feed_entry
from purchase.related_models.purchase_model import Purchase

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Purchase)
def refresh_feed_entries_on_purchase(sender, instance, created, **kwargs):
    """
    Signal handler that refreshes feed entries when a purchase is created or updated.
    This ensures feed entries show the latest purchase information.
    """
    try:
        # The purchased item may not have a feed entry yet or may not be feed-related
        content_type = instance.content_type
        object_id = instance.object_id

        # Get all feed entries related to this purchase's item
        feed_entries = FeedEntry.objects.filter(
            content_type=content_type,
            object_id=object_id,
        )

        if not feed_entries.exists():
            # If the purchase is on a comment or other content that might be part of a
            # parent feed entry, try to get the parent document's feed entries
            if (
                hasattr(instance.item, "unified_document")
                and instance.item.unified_document
            ):
                doc_type = ContentType.objects.get_for_model(
                    instance.item.unified_document
                )
                doc_feed_entries = FeedEntry.objects.filter(
                    content_type=doc_type,
                    object_id=instance.item.unified_document.id,
                )
                feed_entries = feed_entries | doc_feed_entries

        # Update all matching feed entries
        for entry in feed_entries:
            refresh_feed_entry.apply_async(
                args=(entry.id,),
                priority=1,
            )

        # Refresh materialized views if we updated any entries
        if feed_entries.exists():
            FeedEntryLatest.refresh()
            FeedEntryPopular.refresh()

    except Exception as e:
        logger.error(
            f"Error refreshing feed entries for purchase {instance.id}: {str(e)}"
        )
