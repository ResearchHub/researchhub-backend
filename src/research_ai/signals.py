from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from research_ai.models import DocumentInvitedExpert
from research_ai.services.invited_experts_service import (
    get_document_invite_candidates_for_email,
)

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
    When a new user is created, if their email was surfaced for a document
    in expert-finder and they joined within 7 days of that, add a
    DocumentInvitedExpert row for that document.
    """
    if not created:
        return
    email = (getattr(instance, "email", None) or "").strip()
    if not email:
        return
    normalized = email.lower()
    date_joined = getattr(instance, "date_joined", None)
    if not date_joined:
        return

    candidates = get_document_invite_candidates_for_email(normalized, date_joined)
    for unified_document_id, expert_search_id, generated_email_id in candidates:
        DocumentInvitedExpert.objects.get_or_create(
            unified_document_id=unified_document_id,
            user=instance,
            defaults={
                "expert_search_id": expert_search_id,
                "generated_email_id": generated_email_id,
            },
        )
