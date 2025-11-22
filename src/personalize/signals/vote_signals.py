import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from discussion.models import Vote
from personalize.tasks import create_upvote_interaction_task

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Vote, dispatch_uid="personalize_upvote_interaction")
def create_upvote_interaction(sender, instance, created, **kwargs):
    """
    Trigger async creation of UserInteraction when Vote with vote_type=UPVOTE.

    This signal handles internal UPVOTE events and triggers an async Celery task
    to create a UserInteraction record. The UserInteraction will then be synced
    to Personalize via the interaction_signals sync signal.

    The task runs asynchronously to avoid blocking the vote creation endpoint.
    """
    if not created:
        return

    if instance.vote_type != Vote.UPVOTE:
        return

    if not instance.created_by_id:
        logger.debug(
            f"Vote {instance.id} has no created_by user, skipping UserInteraction task"
        )
        return

    try:
        create_upvote_interaction_task.delay(instance.id)
        logger.debug(
            f"Triggered async UserInteraction creation task for UPVOTE: "
            f"vote_id={instance.id}, user_id={instance.created_by_id}"
        )
    except Exception as e:
        logger.error(
            f"Exception triggering UserInteraction creation task for UPVOTE: "
            f"vote_id={instance.id}, error={str(e)}",
            exc_info=True,
        )
        # Don't re-raise - we don't want to break the vote creation process
