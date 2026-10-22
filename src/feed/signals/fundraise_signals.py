import logging
from functools import partial

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from feed.models import FeedEntry
from feed.tasks import create_feed_entry, refresh_feed_entry_by_id
from purchase.related_models.fundraise_model import Fundraise

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Fundraise, dispatch_uid="fundraise_cache_previous_status")
def cache_fundraise_previous_status(sender, instance, **kwargs):
    """Stash prior status so post_save can detect a transition to COMPLETED."""
    if instance.pk is None:
        instance._previous_status = None
        return

    try:
        instance._previous_status = (
            Fundraise.objects.filter(pk=instance.pk)
            .values_list("status", flat=True)
            .get()
        )
    except Fundraise.DoesNotExist:
        instance._previous_status = None


@receiver(post_save, sender=Fundraise, dispatch_uid="fundraise_completed_feed_entry")
def handle_fundraise_completed_feed_entry(sender, instance, created, **kwargs):
    """
    Create a feed entry when a fundraise becomes fully funded (COMPLETED).

    Also refreshes existing document feed entries so proposal cards show the
    updated fundraise status.
    """
    previous_status = getattr(instance, "_previous_status", None)
    if instance.status != Fundraise.COMPLETED:
        return
    if previous_status == Fundraise.COMPLETED:
        return

    try:
        unified_document = instance.unified_document
        if not unified_document:
            logger.warning(
                "No unified document found for completed fundraise %s",
                instance.id,
            )
            return

        content_type = ContentType.objects.get_for_model(instance)
        hub_ids = list(unified_document.hubs.values_list("id", flat=True))
        transaction.on_commit(
            lambda: create_feed_entry.apply_async(
                args=(
                    instance.id,
                    content_type.id,
                    FeedEntry.PUBLISH,
                    hub_ids,
                    instance.created_by_id,
                ),
                priority=1,
            )
        )
        _refresh_document_feed_entries(unified_document)
    except Exception:
        logger.exception(
            "Error creating feed entry for completed fundraise %s",
            instance.id,
        )


def _refresh_document_feed_entries(unified_document):
    """Refresh existing feed entries for a unified document."""
    feed_entries = FeedEntry.objects.filter(unified_document=unified_document)
    if not feed_entries.exists():
        return

    tasks = [
        partial(
            refresh_feed_entry_by_id.apply_async,
            args=(entry.id,),
            priority=1,
        )
        for entry in feed_entries
    ]
    transaction.on_commit(lambda: [task() for task in tasks])
