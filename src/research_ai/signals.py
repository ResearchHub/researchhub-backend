import logging

from django.contrib.auth import get_user_model
from django.db.models import F
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.dateparse import parse_datetime
from django_ses.signals import bounce_received, open_received

from research_ai.models import DocumentInvitedExpert, GeneratedEmail
from research_ai.services.invited_experts_service import (
    get_document_invite_candidates_for_email,
)

User = get_user_model()
logger = logging.getLogger(__name__)


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


@receiver(open_received)
def handle_ses_open_event(
    sender: object,
    mail_obj: dict | None,
    open_obj: dict | None,
    **kwargs,
) -> None:
    """
    Handle SES open event.
    """
    ses_message_id = (mail_obj or {}).get("messageId", "")
    email = _get_generated_email(ses_message_id)
    if email is None:
        return

    # Set opened timestamp and increment open count.
    open_timestamp = parse_datetime((open_obj or {}).get("timestamp", ""))
    update_kwargs: dict = {"open_count": F("open_count") + 1}
    if email.opened_at is None and open_timestamp:
        update_kwargs["opened_at"] = open_timestamp

    GeneratedEmail.objects.filter(id=email.id).update(**update_kwargs)


@receiver(bounce_received)
def handle_ses_bounce_event(
    sender: object,
    mail_obj: dict | None,
    bounce_obj: dict | None,
    **kwargs,
) -> None:
    """
    Handle SES bounce event.
    """
    ses_message_id = (mail_obj or {}).get("messageId", "")
    email = _get_generated_email(ses_message_id)
    if email is None:
        return

    # Set status to bounced and record bounce timestamp.
    bounce_timestamp = parse_datetime((bounce_obj or {}).get("timestamp", ""))
    GeneratedEmail.objects.filter(
        id=email.id,
        status=GeneratedEmail.Status.SENT,
    ).update(
        status=GeneratedEmail.Status.BOUNCED,
        bounced_at=bounce_timestamp,
    )


def _get_generated_email(ses_message_id: str) -> GeneratedEmail | None:
    """
    Look up a `GeneratedEmail` by SES MessageId.
    Returns `None` if not found or on lookup failure.
    """
    if not ses_message_id:
        return None
    try:
        return GeneratedEmail.objects.get(ses_message_id=ses_message_id)
    except GeneratedEmail.DoesNotExist:
        return None
    except GeneratedEmail.MultipleObjectsReturned:
        logger.error("Multiple GeneratedEmail for SES message ID=%s", ses_message_id)
        return None
