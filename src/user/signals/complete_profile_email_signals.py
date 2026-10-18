from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.tasks.complete_profile_email_tasks import send_complete_profile_email_task


@receiver(
    post_save,
    sender=ResearchhubPost,
    dispatch_uid="complete_profile_email_on_note_published",
)
def queue_complete_profile_email_on_note_publish(
    sender: type[ResearchhubPost], instance: ResearchhubPost, created: bool, **kwargs
) -> None:
    """Queue the complete-profile email when a user publishes a notebook note."""
    if not created or instance.note_id is None:
        return
    transaction.on_commit(
        lambda: send_complete_profile_email_task.delay(instance.created_by_id)
    )
