"""Connect, detach, and capacity helpers for Instantly outreach mailboxes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from research_ai.models import OutreachCampaign, OutreachMailbox
from research_ai.services.outreach.instantly_client import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_ERROR,
    ACCOUNT_STATUS_PAUSED,
    DEFAULT_ACCOUNT_DAILY_LIMIT,
    InstantlyClient,
)

if TYPE_CHECKING:
    from user.related_models.user_model import User

logger = logging.getLogger(__name__)


class MailboxError(Exception):
    """Base error for mailbox connect/detach operations."""


class MailboxAlreadyConnectedError(MailboxError):
    """Raised when this editor already has a live mailbox for the address."""


class MailboxOwnedByOtherEditorError(MailboxError):
    """Raised when another editor already owns the Gmail address."""


class MailboxNotFoundError(MailboxError):
    """Raised when the mailbox id is missing or not owned by the editor."""


class InsufficientDailyCapacityError(MailboxError):
    """Raised when a send batch would exceed remaining Instantly capacity."""

    def __init__(self, remaining: int, requested: int):
        self.remaining = remaining
        self.requested = requested
        super().__init__(
            f"Requested {requested} leads exceeds remaining daily capacity "
            f"of {remaining}."
        )


class OutreachMailboxService:
    """Editor Gmail connect/detach and Instantly remaining-capacity checks."""

    def __init__(self, *, client: InstantlyClient | None = None):
        self.client = client if client is not None else InstantlyClient()

    def connect_mailbox(
        self,
        editor: User,
        *,
        email: str,
        app_password: str,
    ) -> OutreachMailbox:
        """
        Create the Instantly account, confirm it, and persist/restore a mailbox.

        The Google app password is sent to Instantly and never stored locally.
        """
        normalized = normalize_gmail_address(email)
        if not normalized or not app_password:
            raise MailboxError("Gmail address and app password are required.")

        existing = OutreachMailbox.all_objects.filter(email=normalized).first()
        if existing is not None and existing.editor_id != editor.id:
            raise MailboxOwnedByOtherEditorError(
                "This Gmail address is already connected by another editor."
            )
        if existing is not None and not existing.is_removed:
            raise MailboxAlreadyConnectedError(
                "This Gmail address is already connected."
            )

        first_name, last_name = editor_display_names(editor)
        self.client.create_gmail_account(
            email=normalized,
            first_name=first_name,
            last_name=last_name,
            app_password=app_password,
            daily_limit=DEFAULT_ACCOUNT_DAILY_LIMIT,
            enable_slow_ramp=True,
        )
        account = self.client.get_account(normalized)
        status = mailbox_status_from_instantly(account.get("status"))
        daily_limit = int(account.get("daily_limit") or DEFAULT_ACCOUNT_DAILY_LIMIT)
        provider_code = int(
            account.get("provider_code")
            or OutreachMailbox._meta.get_field("provider_code").default
        )

        with transaction.atomic():
            if existing is None:
                mailbox = OutreachMailbox.objects.create(
                    editor=editor,
                    email=normalized,
                    provider_code=provider_code,
                    status=status,
                    daily_limit=daily_limit,
                )
            else:
                mailbox = existing
                mailbox.editor = editor
                mailbox.provider_code = provider_code
                mailbox.status = status
                mailbox.daily_limit = daily_limit
                mailbox.is_removed = False
                mailbox.is_public = True
                mailbox.is_removed_date = None
                mailbox.save(
                    update_fields=[
                        "editor",
                        "provider_code",
                        "status",
                        "daily_limit",
                        "is_removed",
                        "is_public",
                        "is_removed_date",
                        "updated_date",
                    ]
                )
        return mailbox

    def detach_mailbox(self, editor: User, mailbox_id: int) -> OutreachMailbox:
        """
        Remove a mailbox from Instantly campaigns, delete the Instantly account,
        and soft-delete the local row. Campaign and send history are kept.
        """
        with transaction.atomic():
            mailbox = (
                OutreachMailbox.objects.select_for_update()
                .filter(id=mailbox_id, editor=editor)
                .first()
            )
            if mailbox is None:
                raise MailboxNotFoundError("Outreach mailbox not found.")

            mailbox.status = OutreachMailbox.Status.DISCONNECTING
            mailbox.save(update_fields=["status", "updated_date"])

            remaining_emails = list(
                OutreachMailbox.objects.filter(
                    editor=editor,
                    status=OutreachMailbox.Status.ACTIVE,
                )
                .exclude(id=mailbox.id)
                .values_list("email", flat=True)
            )
            remaining_limit = DEFAULT_ACCOUNT_DAILY_LIMIT * len(remaining_emails)

            campaigns = list(
                OutreachCampaign.objects.select_for_update().filter(editor=editor)
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

            self.client.delete_account(mailbox.email)

            mailbox.status = OutreachMailbox.Status.DISCONNECTED
            mailbox.save(update_fields=["status", "updated_date"])
            mailbox.delete(soft=True)
            return mailbox

    def get_capacity_summary(self, editor: User) -> dict:
        """
        Editor-level and per-mailbox daily send capacity for settings / send UI.

        Instantly daily analytics are only queried for active mailboxes.
        Non-active mailboxes are included with ``sent_today`` /
        ``remaining_today`` of 0 so the UI can still show error/disconnected
        rows without treating them as sendable capacity.
        """
        mailboxes = list(
            OutreachMailbox.objects.filter(editor=editor).order_by("-created_date")
        )
        active = [m for m in mailboxes if m.status == OutreachMailbox.Status.ACTIVE]
        sent_by_email: dict[str, int] = {}
        if active:
            today = timezone.localdate().isoformat()
            analytics = self.client.get_daily_account_analytics(
                [m.email for m in active],
                start_date=today,
                end_date=today,
            )
            for row in analytics:
                if not isinstance(row, dict):
                    continue
                if row.get("date") and row.get("date") != today:
                    continue
                account = row.get("email_account")
                if not account:
                    continue
                sent_by_email[str(account).lower()] = int(row.get("sent") or 0)

        mailbox_rows: list[dict] = []
        sent_today_total = 0
        remaining_today = 0
        daily_limit_total = 0
        for mailbox in mailboxes:
            is_active = mailbox.status == OutreachMailbox.Status.ACTIVE
            sent = sent_by_email.get(mailbox.email.lower(), 0) if is_active else 0
            remaining = max(0, mailbox.daily_limit - sent) if is_active else 0
            if is_active:
                daily_limit_total += mailbox.daily_limit
                sent_today_total += sent
                remaining_today += remaining
            mailbox_rows.append(
                {
                    "email": mailbox.email,
                    "status": mailbox.status,
                    "daily_limit": mailbox.daily_limit,
                    "sent_today": sent,
                    "remaining_today": remaining,
                }
            )

        return {
            "active_mailbox_count": len(active),
            "daily_limit_total": daily_limit_total,
            "sent_today": sent_today_total,
            "remaining_today": remaining_today,
            "mailboxes": mailbox_rows,
        }

    def get_remaining_daily_capacity(self, editor: User) -> int:
        """Sum of (daily_limit - sent_today) across the editor's active mailboxes."""
        return int(self.get_capacity_summary(editor)["remaining_today"])

    def assert_within_daily_capacity(self, editor: User, lead_count: int) -> int:
        """
        Return remaining capacity, or raise if ``lead_count`` would exceed it.
        """
        remaining = self.get_remaining_daily_capacity(editor)
        if lead_count > remaining:
            raise InsufficientDailyCapacityError(remaining, lead_count)
        return remaining


def normalize_gmail_address(email: str) -> str:
    return (email or "").strip().lower()


def editor_display_names(editor: User) -> tuple[str, str]:
    """Prefer author_profile names; fall back to User names."""
    author = getattr(editor, "author_profile", None)
    if author is not None:
        first = (author.first_name or "").strip()
        last = (author.last_name or "").strip()
        if first or last:
            return first or "Editor", last or "User"
    first = (editor.first_name or "").strip()
    last = (editor.last_name or "").strip()
    return first or "Editor", last or "User"


def mailbox_status_from_instantly(instantly_status: object) -> str:
    """
    Map Instantly account status to ``OutreachMailbox.Status``.

    Active (1) stays active. Paused (2, 3) is excluded from sending by storing
    as error (no local paused status). Negative codes are connection/bounce/
    sending errors.
    """
    try:
        status = int(instantly_status)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return OutreachMailbox.Status.ERROR

    if status == ACCOUNT_STATUS_ACTIVE:
        return OutreachMailbox.Status.ACTIVE
    if status in ACCOUNT_STATUS_PAUSED or status in ACCOUNT_STATUS_ERROR:
        return OutreachMailbox.Status.ERROR
    return OutreachMailbox.Status.ERROR
