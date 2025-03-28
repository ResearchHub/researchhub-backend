import logging
from functools import partial

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from feed.models import FeedEntry
from feed.tasks import create_feed_entry, delete_feed_entry
from reputation.related_models.bounty import Bounty

"""
Signal handlers for Bounty model.

The signal handlers are responsbile for creating and deleting feed entries
when bounties are opened and closed, respectively.
"""

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Bounty, dispatch_uid="bounty_create_feed_entry")
def handle_bounty_create_feed_entry(sender, instance, **kwargs):
    """
    When a bounty is opened, create feed entries for all hubs associated with the
    researchhub document that the bounty is associated with.
    """
    try:
        _create_bounty_feed_entries(instance)
    except Exception as e:
        logger.error(f"Failed to create feed entry for bounty {instance.id}: {e}")


@receiver(post_save, sender=Bounty, dispatch_uid="bounty_delete_feed_entry")
def handle_bounty_delete_feed_entry(sender, instance, **kwargs):
    """
    When a bounty is closed, delete all feed entries associated with the bounty.
    """
    try:
        _delete_bounty_feed_entries(instance)
    except Exception as e:
        logger.error(f"Failed to delete feed entry for bounty {instance.id}: {e}")


def _create_bounty_feed_entries(bounty):
    """
    Create feed entries for all hubs associated with the bounty's unified document.
    """
    parent_bounty = bounty
    if bounty.parent:
        parent_bounty = (
            bounty.parent
        )  # only original bounties create feed entries, contributions just update the amount

    if parent_bounty.status == Bounty.OPEN:
        tasks = [
            partial(
                create_feed_entry.apply_async,
                args=(
                    parent_bounty.id,
                    ContentType.objects.get_for_model(parent_bounty).id,
                    FeedEntry.OPEN,
                    hub.id,
                    ContentType.objects.get_for_model(hub).id,
                    parent_bounty.created_by.id,
                ),
                priority=1,
            )
            for hub in parent_bounty.unified_document.hubs.all()
        ]
        transaction.on_commit(lambda: [task() for task in tasks])


def _delete_bounty_feed_entries(bounty):
    """
    Delete feed entries for all hubs associated with the bounty's unified document.
    """
    if bounty.status in [Bounty.CANCELLED, Bounty.CLOSED, Bounty.EXPIRED]:
        tasks = [
            partial(
                delete_feed_entry.apply_async,
                args=(
                    bounty.id,
                    ContentType.objects.get_for_model(bounty).id,
                    hub.id,
                    ContentType.objects.get_for_model(hub).id,
                ),
                priority=1,
            )
            for hub in bounty.unified_document.hubs.all()
        ]
        transaction.on_commit(lambda: [task() for task in tasks])
