"""Process Instantly outreach webhook events."""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from research_ai.models import GeneratedEmail, OutreachCampaign, OutreachMailbox
from research_ai.services.expert_finder.display import ExpertDisplay
from research_ai.services.expert_finder.persist import ExpertPersist
from research_ai.services.outreach.instantly_client import (
    DEFAULT_ACCOUNT_DAILY_LIMIT,
    InstantlyClient,
)
from research_ai.services.outreach.invited_experts import (
    grant_invited_expert_access_for_send,
)
from research_ai.services.outreach.mailbox_service import normalize_gmail_address

logger = logging.getLogger(__name__)

LEAD_EVENT_TYPES = frozenset(
    {
        "email_sent",
        "email_opened",
        "email_bounced",
        "reply_received",
    }
)


class InstantlyWebhookService:
    """Apply Instantly status webhooks to GeneratedEmail / OutreachMailbox rows."""

    def __init__(self, *, client: InstantlyClient | None = None):
        self.client = client if client is not None else InstantlyClient()

    def handle_event(self, payload: dict[str, Any]) -> str:
        """
        Process one webhook payload.

        Returns a short disposition string for logging/response. Unknown events
        are ignored (caller should still return HTTP 200).
        """
        if not isinstance(payload, dict):
            return "ignored_invalid_payload"

        event_type = str(payload.get("event_type") or "").strip()
        if event_type == "account_error":
            return self._handle_account_error(payload)
        if event_type in LEAD_EVENT_TYPES:
            return self._handle_lead_event(event_type, payload)
        return "ignored_unknown_event"

    def _handle_lead_event(self, event_type: str, payload: dict[str, Any]) -> str:
        campaign_id = str(payload.get("campaign_id") or "").strip()
        lead_email = ExpertDisplay.normalize_email(str(payload.get("lead_email") or ""))
        if not campaign_id or not lead_email:
            return "ignored_missing_lead_fields"

        email = (
            GeneratedEmail.objects.filter(
                outreach_campaign__external_campaign_id=campaign_id,
                expert_email__iexact=lead_email,
            )
            .order_by("-created_date")
            .first()
        )
        if email is None:
            return "ignored_unknown_lead"

        event_time = _event_timestamp(payload)
        if event_type == "email_sent":
            return self._apply_email_sent(email, payload, event_time)
        if event_type == "email_opened":
            return self._apply_email_opened(email, event_time)
        if event_type == "email_bounced":
            return self._apply_email_bounced(email, event_time)
        if event_type == "reply_received":
            return self._apply_reply_received(email, event_time)
        return "ignored_unknown_event"

    def _apply_email_sent(
        self,
        email: GeneratedEmail,
        payload: dict[str, Any],
        event_time,
    ) -> str:
        if email.sent_at is not None and email.status == GeneratedEmail.Status.SENT:
            return "email_sent_idempotent"

        sender = normalize_gmail_address(str(payload.get("email_account") or ""))
        update_fields: dict[str, Any] = {
            "status": GeneratedEmail.Status.SENT,
            "channels": [GeneratedEmail.Channel.EMAIL],
            "sent_at": email.sent_at or event_time or timezone.now(),
            "updated_date": timezone.now(),
        }
        if sender and not (email.sender_account or "").strip():
            update_fields["sender_account"] = sender

        GeneratedEmail.objects.filter(id=email.id).update(**update_fields)
        email.refresh_from_db()
        ExpertPersist.mark_last_email_sent_at(email.expert_email or "")
        try:
            grant_invited_expert_access_for_send(generated_email=email)
        except Exception:
            logger.exception(
                "Grant access on Instantly email_sent failed id=%s", email.id
            )
        return "email_sent"

    def _apply_email_opened(self, email: GeneratedEmail, event_time) -> str:
        update_kwargs: dict[str, Any] = {
            "open_count": F("open_count") + 1,
            "updated_date": timezone.now(),
        }
        if email.opened_at is None:
            update_kwargs["opened_at"] = event_time or timezone.now()
        GeneratedEmail.objects.filter(id=email.id).update(**update_kwargs)
        return "email_opened"

    def _apply_email_bounced(self, email: GeneratedEmail, event_time) -> str:
        GeneratedEmail.objects.filter(id=email.id).update(
            status=GeneratedEmail.Status.BOUNCED,
            bounced_at=email.bounced_at or event_time or timezone.now(),
            updated_date=timezone.now(),
        )
        return "email_bounced"

    def _apply_reply_received(self, email: GeneratedEmail, event_time) -> str:
        if email.replied_at is not None:
            return "reply_received_idempotent"
        GeneratedEmail.objects.filter(id=email.id, replied_at__isnull=True).update(
            replied_at=event_time or timezone.now(),
            updated_date=timezone.now(),
        )
        return "reply_received"

    def _handle_account_error(self, payload: dict[str, Any]) -> str:
        account = normalize_gmail_address(str(payload.get("email_account") or ""))
        if not account:
            return "ignored_missing_account"

        with transaction.atomic():
            mailbox = (
                OutreachMailbox.objects.select_for_update()
                .filter(email=account)
                .first()
            )
            if mailbox is None:
                return "ignored_unknown_account"

            if mailbox.status == OutreachMailbox.Status.ERROR:
                return "account_error_idempotent"

            mailbox.status = OutreachMailbox.Status.ERROR
            mailbox.save(update_fields=["status", "updated_date"])

            remaining_emails = list(
                OutreachMailbox.objects.filter(
                    editor_id=mailbox.editor_id,
                    status=OutreachMailbox.Status.ACTIVE,
                )
                .exclude(id=mailbox.id)
                .values_list("email", flat=True)
            )
            remaining_limit = DEFAULT_ACCOUNT_DAILY_LIMIT * len(remaining_emails)

            campaigns = list(
                OutreachCampaign.objects.select_for_update().filter(
                    editor_id=mailbox.editor_id
                )
            )
            for campaign in campaigns:
                if not campaign.external_campaign_id:
                    if not remaining_emails:
                        campaign.status = OutreachCampaign.Status.NO_ACTIVE_MAILBOXES
                        campaign.save(update_fields=["status", "updated_date"])
                    continue
                self.client.update_campaign(
                    campaign.external_campaign_id,
                    email_list=remaining_emails,
                    daily_limit=remaining_limit,
                )
                if not remaining_emails:
                    self.client.pause_campaign(campaign.external_campaign_id)
                    campaign.status = OutreachCampaign.Status.NO_ACTIVE_MAILBOXES
                    campaign.save(update_fields=["status", "updated_date"])

        return "account_error"


def _event_timestamp(payload: dict[str, Any]):
    raw = payload.get("timestamp")
    if not raw:
        return None
    parsed = parse_datetime(str(raw))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.utc)
    return parsed
