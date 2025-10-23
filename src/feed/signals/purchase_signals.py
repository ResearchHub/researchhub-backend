import logging
from functools import partial

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from feed.models import FeedEntry
from feed.tasks import refresh_feed_entry
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.purchase_model import Purchase
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Purchase)
def refresh_feed_entries_on_purchase(sender, instance, created, **kwargs):
    """
    Signal handler that refreshes feed entries when a purchase is created or updated.
    This ensures feed entries show the latest purchase information.

    For fundraise contributions, we need to find feed entries via the unified document
    since contributions are linked to Fundraise objects, but feed entries are created
    for Post objects.
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

            # Find all feed entries for this unified document
            feed_entries = FeedEntry.objects.filter(unified_document=unified_document)

            if not feed_entries.exists():
                return

            # Update all matching feed entries
            tasks = [
                partial(
                    refresh_feed_entry.apply_async,
                    args=(entry.id,),
                    priority=1,
                )
                for entry in feed_entries
            ]
            transaction.on_commit(lambda: [task() for task in tasks])

        else:
            # For non-fundraise purchases, use the original logic
            feed_entries = FeedEntry.objects.filter(
                content_type=instance.content_type,
                object_id=instance.object_id,
            )
            if not feed_entries.exists():
                return

            # Update all matching feed entries
            tasks = [
                partial(
                    refresh_feed_entry.apply_async,
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
                refresh_feed_entry.apply_async,
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
                refresh_feed_entry.apply_async,
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
