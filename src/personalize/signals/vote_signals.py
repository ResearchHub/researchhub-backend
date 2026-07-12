import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from discussion.models import Vote
from personalize.tasks import create_upvote_interaction_task

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Vote, dispatch_uid="personalize_upvote_interaction")
def create_upvote_interaction(sender, instance, created, **kwargs):
    """
    Trigger creation of UserInteraction when Vote with vote_type=UPVOTE.
    """
    if not created:
        return

    if instance.vote_type != Vote.UPVOTE:
        return

    if not instance.created_by_id:
        logger.info(
            "Vote %s has no created_by user, skipping UserInteraction task", instance.id
        )
        return

    def trigger_task():
        try:
            create_upvote_interaction_task.delay(instance.id)
        except Exception:
            logger.exception(
                "Failed to create upvote interaction for vote %s", instance.id
            )

    transaction.on_commit(trigger_task)
