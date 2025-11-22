import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from analytics.models import UserInteractions
from personalize.tasks import sync_interaction_event_to_personalize_task

logger = logging.getLogger(__name__)


@receiver(
    post_save, sender=UserInteractions, dispatch_uid="personalize_sync_interaction"
)
def sync_interaction_to_personalize(sender, instance, created, **kwargs):
    """
    Sync newly created UserInteractions to Personalize.

    This signal handles syncing all UserInteractions (from both internal events
    like UPVOTE and external events from Amplitude) to Personalize.

    The sync happens asynchronously via Celery task.
    """
    if not created:
        return

    if not instance.unified_document_id:
        logger.debug(
            f"UserInteraction {instance.id} missing unified_document_id, "
            f"skipping Personalize sync"
        )
        return

    if not instance.user_id and not instance.external_user_id:
        logger.debug(
            f"UserInteraction {instance.id} missing both user_id and external_user_id, "
            f"skipping Personalize sync"
        )
        return

    try:
        sync_interaction_event_to_personalize_task.delay(instance.id)
        logger.debug(
            f"Triggered Personalize sync task for UserInteraction {instance.id} "
            f"(event={instance.event}, user_id={instance.user_id}, "
            f"external_user_id={instance.external_user_id})"
        )
    except Exception as e:
        logger.error(
            f"Exception triggering Personalize sync task for UserInteraction "
            f"{instance.id}: {str(e)}",
            exc_info=True,
        )
        # Don't re-raise - we don't want to break the UserInteraction creation process
