import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from personalize.tasks import create_comment_interaction_task
from researchhub_comment.models import RhCommentModel
from utils.sentry import log_error

logger = logging.getLogger(__name__)


@receiver(
    post_save, sender=RhCommentModel, dispatch_uid="personalize_comment_interaction"
)
def create_comment_interaction(sender, instance, created, **kwargs):
    """
    Trigger UserInteraction creation when a comment is created.
    """
    if not created:
        return

    try:
        _trigger_comment_interaction_task(instance)
    except Exception as e:
        log_error(
            e,
            message=f"Failed to trigger interaction task for comment {instance.id}",
        )


def _trigger_comment_interaction_task(comment):
    """
    Schedule an async task to create a UserInteraction for the comment.

    Raises:
        ValueError: If comment is missing created_by_id
    """
    if not comment.created_by_id:
        raise ValueError(
            f"Comment {comment.id} has no created_by user, "
            f"skipping UserInteraction task"
        )

    transaction.on_commit(lambda: create_comment_interaction_task.delay(comment.id))
