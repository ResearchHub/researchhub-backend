import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from personalize.tasks import create_comment_interaction_task
from researchhub_comment.models import RhCommentModel
from utils.sentry import log_error, log_info

logger = logging.getLogger(__name__)


@receiver(
    post_save, sender=RhCommentModel, dispatch_uid="personalize_comment_interaction"
)
def create_comment_interaction(sender, instance, created, **kwargs):
    if not created:
        return

    if not instance.created_by_id:
        log_info(
            f"Comment {instance.id} has no created_by user, skipping UserInteraction task"
        )
        return

    def trigger_task():
        try:
            create_comment_interaction_task.delay(instance.id)
        except Exception as e:
            log_error(
                e,
                message=(
                    f"Exception triggering UserInteraction creation task for Comment: "
                    f"comment_id={instance.id}"
                ),
            )

    transaction.on_commit(trigger_task)
