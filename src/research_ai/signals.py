from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from research_ai.tasks import materialize_document_invited_experts_async

User = get_user_model()


@receiver(
    post_save,
    sender=User,
    dispatch_uid="research_ai_document_invited_expert_on_user_created",
)
def on_user_created_maybe_add_document_invited_expert(
    sender, instance, created, **kwargs
):
    """
    When a new user is created, enqueue work to link ``Expert.registered_user`` when
    outreach qualifies and to add ``DocumentInvitedExpert`` rows for matching documents.
    """
    if not created:
        return
    email = (getattr(instance, "email", None) or "").strip()
    if not email:
        return
    normalized = email.lower()
    materialize_document_invited_experts_async.delay(
        normalized_email=normalized,
        user_id=instance.pk,
    )
