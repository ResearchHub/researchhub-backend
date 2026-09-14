import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from feed.models import FeedEntry
from feed.tasks import create_feed_entry
from user.related_models.funding_activity_model import FundingActivity

logger = logging.getLogger(__name__)

FINANCIAL_FEED_SOURCE_TYPES = (
    FundingActivity.BOUNTY_PAYOUT,
    FundingActivity.TIP_REVIEW,
)


@receiver(post_save, sender=FundingActivity)
def handle_funding_activity_feed_entry(sender, instance, created, **kwargs):
    """
    Create a feed entry when a bounty payout or review tip FundingActivity
    is created.
    """
    if not created:
        return
    if instance.source_type not in FINANCIAL_FEED_SOURCE_TYPES:
        return

    try:
        if instance.unified_document_id:
            hub_ids = list(instance.unified_document.hubs.values_list("id", flat=True))
        else:
            hub_ids = []

        content_type = ContentType.objects.get_for_model(instance)
        transaction.on_commit(
            lambda: create_feed_entry.apply_async(
                args=(
                    instance.id,
                    content_type.id,
                    FeedEntry.PUBLISH,
                    hub_ids,
                    instance.funder_id,
                ),
                priority=1,
            )
        )
    except Exception:
        logger.exception(
            "Error creating feed entry for FundingActivity %s",
            instance.id,
        )
