import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from feed.models import FeedEntry
from feed.tasks import create_feed_entry
from user.related_models.funding_activity_model import FundingActivity

logger = logging.getLogger(__name__)

FEED_SOURCE_TYPES = frozenset(
    {
        FundingActivity.BOUNTY_PAYOUT,
        FundingActivity.TIP_REVIEW,
    }
)


@receiver(post_save, sender=FundingActivity)
def handle_funding_activity_feed_entry(sender, instance, created, **kwargs):
    """
    When a bounty payout or review tip FundingActivity is created,
    schedule a dedicated feed entry for the financial activity feed.
    """
    if not created:
        return

    if instance.source_type not in FEED_SOURCE_TYPES:
        return

    try:
        unified_document = instance.unified_document
        if not unified_document:
            logger.warning(
                f"No unified document found for funding activity {instance.id}"
            )
            return

        _create_funding_activity_feed_entry(instance, unified_document)

    except Exception as e:
        logger.error(
            f"Error handling feed entry for funding activity {instance.id}: {str(e)}"
        )


def _create_funding_activity_feed_entry(activity, unified_document):
    """
    Create a feed entry for a bounty payout or review tip.
    """
    content_type = ContentType.objects.get_for_model(activity)
    hub_ids = list(unified_document.hubs.values_list("id", flat=True))
    transaction.on_commit(
        lambda: create_feed_entry.apply_async(
            args=(
                activity.id,
                content_type.id,
                FeedEntry.PUBLISH,
                hub_ids,
                activity.funder_id,
            ),
            priority=1,
        )
    )
