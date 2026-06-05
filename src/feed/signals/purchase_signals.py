import logging
from functools import partial

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from feed.models import FeedEntry
from feed.tasks import create_feed_entry, refresh_feed_entry_by_id
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.purchase_model import Purchase
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Purchase)
def handle_purchase_feed_entry(sender, instance, created, **kwargs):
    """
    Signal handler that refreshes feed entries when a purchase is created or updated.
    This ensures feed entries show the latest purchase information.

    For fundraise contributions, we also create a dedicated feed entry
    so the contribution appears as its own activity in the feed.
    """
    try:
        # Handle fundraise contributions differently
        if instance.purchase_type == Purchase.FUNDRAISE_CONTRIBUTION:
            # Import here to avoid circular imports
            from purchase.models import Fundraise

            # Get the fundraise object
            try:
                fundraise = Fundraise.objects.get(id=instance.object_id)
            except Fundraise.DoesNotExist:
                logger.warning(
                    f"Fundraise {instance.object_id} not found for purchase {instance.id}"
                )
                return

            # Get the unified document
            unified_document = fundraise.unified_document
            if not unified_document:
                logger.warning(
                    f"No unified document found for fundraise {fundraise.id}"
                )
                return

            # Create a new feed entry for this contribution
            if created:
                _create_contribution_feed_entry(instance, unified_document)

            # Refresh existing document feed entries
            _refresh_document_feed_entries(unified_document)
        else:
            # For non-fundraise purchases, use direct lookup
            feed_entries = FeedEntry.objects.filter(
                content_type=instance.content_type,
                object_id=instance.object_id,
            )

            if feed_entries.exists():
                # Update all matching feed entries
                tasks = [
                    partial(
                        refresh_feed_entry_by_id.apply_async,
                        args=(entry.id,),
                        priority=1,
                    )
                    for entry in feed_entries
                ]
                transaction.on_commit(lambda: [task() for task in tasks])

    except Exception as e:
        logger.error(
            f"Error refreshing feed entries for purchase {instance.id}: {str(e)}"
        )


@receiver(post_save, sender=UsdFundraiseContribution)
def handle_usd_contribution_feed_entry(sender, instance, created, **kwargs):
    """
    When a USD fundraise contribution is created, create a new
    feed entry for it and refresh existing document feed entries.
    """
    if not created:
        return

    try:
        fundraise = instance.fundraise
        unified_document = fundraise.unified_document
        if not unified_document:
            logger.warning(f"No unified document found for fundraise {fundraise.id}")
            return

        _create_contribution_feed_entry(instance, unified_document)
        _refresh_document_feed_entries(unified_document)

    except Exception as e:
        logger.error(
            f"Error handling feed entry for USD contribution {instance.id}: {str(e)}"
        )


def _create_contribution_feed_entry(instance, unified_document):
    """
    Create a feed entry for a fundraise contribution.
    """
    content_type = ContentType.objects.get_for_model(instance)
    hub_ids = list(unified_document.hubs.values_list("id", flat=True))
    transaction.on_commit(
        lambda: create_feed_entry.apply_async(
            args=(
                instance.id,
                content_type.id,
                FeedEntry.PUBLISH,
                hub_ids,
                instance.user.id,
            ),
            priority=1,
        )
    )


def _refresh_document_feed_entries(unified_document):
    """
    Refresh existing feed entries for a unified document.
    """
    feed_entries = FeedEntry.objects.filter(unified_document=unified_document)
    if feed_entries.exists():
        tasks = [
            partial(
                refresh_feed_entry_by_id.apply_async,
                args=(entry.id,),
                priority=1,
            )
            for entry in feed_entries
        ]
        transaction.on_commit(lambda: [task() for task in tasks])


@receiver(post_save, sender=GrantApplication)
def refresh_feed_entries_on_grant_application(sender, instance, created, **kwargs):
    """
    Signal handler that refreshes feed entries when a grant application is created or updated.
    This ensures feed entries show the latest application information for grants.
    """
    try:
        # Get the grant's unified document (the post the grant is related to)
        grant = instance.grant
        unified_document = grant.unified_document

        if not unified_document:
            return

        # Find feed entries for the post that the grant is related to
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        feed_entries = FeedEntry.objects.filter(
            unified_document=unified_document,
            content_type=post_content_type,
        )

        if not feed_entries.exists():
            return

        # Update all matching feed entries to reflect the new application data
        tasks = [
            partial(
                refresh_feed_entry_by_id.apply_async,
                args=(entry.id,),
                priority=1,
            )
            for entry in feed_entries
        ]
        transaction.on_commit(lambda: [task() for task in tasks])

    except Exception as e:
        logger.error(
            f"Error refreshing feed entries for grant application {instance.id}: {str(e)}"
        )


@receiver(post_delete, sender=GrantApplication)
def refresh_feed_entries_on_grant_application_delete(sender, instance, **kwargs):
    """
    Signal handler that refreshes feed entries when a grant application is deleted.
    This ensures feed entries are updated to reflect the removal of the application.
    """
    try:
        # Get the grant's unified document (the post the grant is related to)
        grant = instance.grant
        unified_document = grant.unified_document

        if not unified_document:
            return

        # Find feed entries for the post that the grant is related to
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        feed_entries = FeedEntry.objects.filter(
            unified_document=unified_document,
            content_type=post_content_type,
        )

        if not feed_entries.exists():
            return

        # Update all matching feed entries to reflect the removed application
        tasks = [
            partial(
                refresh_feed_entry_by_id.apply_async,
                args=(entry.id,),
                priority=1,
            )
            for entry in feed_entries
        ]
        transaction.on_commit(lambda: [task() for task in tasks])

    except Exception as e:
        logger.error(
            f"Error refreshing feed entries for deleted grant application {instance.id}: {str(e)}"
        )
