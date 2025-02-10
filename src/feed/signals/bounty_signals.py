from django.contrib.contenttypes.models import ContentType
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


@receiver(post_save, sender=Bounty, dispatch_uid="bounty_create_feed_entry")
def handle_bounty_create_feed_entry(sender, instance, **kwargs):
    """
    When a bounty is opened, create feed entries for all hubs associated with the
    researchhub document that the bounty is associated with.
    """
    bounty = instance
    if bounty.status == Bounty.OPEN:
        for hub in bounty.unified_document.hubs.all():
            create_feed_entry.apply_async(
                args=(
                    bounty.id,
                    ContentType.objects.get_for_model(bounty).id,
                    FeedEntry.OPEN,
                    hub.id,
                    ContentType.objects.get_for_model(hub).id,
                ),
                priority=1,
            )


@receiver(post_save, sender=Bounty, dispatch_uid="bounty_delete_feed_entry")
def handle_boundy_closed_feed_entry(sender, instance, **kwargs):
    """
    When a bounty is closed, delete all feed entries associated with the bounty.
    """
    bounty = instance
    if bounty.status in [Bounty.CANCELLED, Bounty.CLOSED, Bounty.EXPIRED]:
        for hub in bounty.unified_document.hubs.all():
            delete_feed_entry.apply_async(
                args=(
                    bounty.id,
                    ContentType.objects.get_for_model(bounty).id,
                    hub.id,
                    ContentType.objects.get_for_model(hub).id,
                ),
                priority=1,
            )
