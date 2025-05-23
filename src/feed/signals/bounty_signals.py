import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from feed.tasks import refresh_feed_entries_for_objects
from reputation.related_models.bounty import Bounty

"""
Signal handlers for Bounty model.

The signal handlers are responsible for updating feed entries for posts and papers
when bounties are added, updated, or removed.
"""

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Bounty, dispatch_uid="bounty_update_feed_entries")
def handle_bounty_update_feed_entries(sender, instance, created, **kwargs):
    """
    When a bounty is created or updated, update the feed entries for the associated
    paper or post to reflect the bounty status.
    """
    try:
        _update_associated_document_feed_entries(instance)
    except Exception as e:
        logger.error(f"Failed to update feed entries for bounty {instance.id}: {e}")


@receiver(post_delete, sender=Bounty, dispatch_uid="bounty_delete_update_feed_entries")
def handle_bounty_delete_update_feed_entries(sender, instance, **kwargs):
    """
    When a bounty is deleted, update the feed entries for the associated
    paper or post to reflect the bounty status.
    """
    try:
        _update_associated_document_feed_entries(instance)
    except Exception as e:
        logger.error(
            f"Failed to update feed entries for deleted bounty {instance.id}: {e}"
        )


def _update_associated_document_feed_entries(bounty):
    """
    Updates the feed entries for the paper or post associated with the bounty.
    The update is scheduled to run after the current transaction is committed.
    """
    unified_document = bounty.unified_document
    if not unified_document:
        logger.warning(f"No unified document found for bounty {bounty.id}")
        return

    try:
        document = unified_document.get_document()
        document_content_type = ContentType.objects.get_for_model(document)

        transaction.on_commit(
            lambda: refresh_feed_entries_for_objects.apply_async(
                args=(document.id, document_content_type.id),
                priority=1,
            )
        )
    except Exception as e:
        logger.warning(
            f"Failed to update feed entries associated with unified document {unified_document.id}: {e}"
        )
        return
