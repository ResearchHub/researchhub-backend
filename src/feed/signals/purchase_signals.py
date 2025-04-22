import logging

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
        # Get the a feed entry for this object, then get the unified document
        # to find all feed entries that may be affected by the purchase
        feed_entries = FeedEntry.objects.filter(
            content_type=instance.content_type,
            object_id=instance.object_id,
        )
        if not feed_entries.exists():
            return

        # Update all matching feed entries
        for entry in feed_entries:
            refresh_feed_entry.apply_async(
                args=(entry.id,),
                priority=1,
            )

    except Exception as e:
        logger.error(
            f"Error refreshing feed entries for purchase {instance.id}: {str(e)}"
        )
