"""Connect, detach, and capacity helpers for outreach mailboxes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from research_ai.models import GeneratedEmail, OutreachCampaign, OutreachMailbox
from research_ai.services.outreach.instantly_client import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_ERROR,
    ACCOUNT_STATUS_PAUSED,
    DEFAULT_ACCOUNT_DAILY_LIMIT,
    WARMUP_STATUS_ACTIVE,
    InstantlyAPIError,
    InstantlyClient,
    InstantlyNotFoundError,
)

if TYPE_CHECKING:
    from user.related_models.user_model import User

logger = logging.getLogger(__name__)

MAX_MAILBOX_DAILY_LIMIT = 10_000

OAUTH_SESSION_TTL_SECONDS = 600
OAUTH_PENDING_KEY = "outreach:oauth:pending:{session_id}"
OAUTH_DONE_KEY = "outreach:oauth:done:{session_id}"

_UNSET = object()


class MailboxError(Exception):
    """Base error for mailbox connect/detach operations."""


class MailboxAlreadyConnectedError(MailboxError):
    """Raised when this editor already has a live mailbox for the address."""


class MailboxOwnedByOtherEditorError(MailboxError):
    """Raised when another editor already owns the email address."""


class MailboxNotFoundError(MailboxError):
    """Raised when the mailbox id is missing or not owned by the editor."""


class MailboxOAuthSessionNotFoundError(MailboxError):
    """Raised when an OAuth session is missing or not owned by this editor."""


def active_mailboxes_for_editor(editor: User | int):
    """Active mailboxes for an editor (User or editor id)."""
    editor_id = editor if isinstance(editor, int) else editor.id
    return OutreachMailbox.objects.filter(
        editor_id=editor_id,
        status=OutreachMailbox.Status.ACTIVE,
    ).order_by("email")


class OutreachMailboxService:
    """Editor mailbox connect/detach (app password + OAuth) and capacity."""

    def __init__(self, *, client: InstantlyClient | None = None):
        self.client = client if client is not None else InstantlyClient()

    def connect_mailbox(
        self,
        editor: User,
        *,
        email: str,
        app_password: str,
        reply_to: str | None = None,
    ) -> OutreachMailbox:
        """
        Create the Instantly account, confirm it, and persist/restore a mailbox.

        The Google app password is sent to Instantly and never stored locally.
        Optional ``reply_to`` is sent to Instantly and cached locally.
        """
        normalized = normalize_mailbox_email(email)
        if not normalized or not app_password:
            raise MailboxError("Gmail address and app password are required.")
        normalized_reply_to = normalize_reply_to(reply_to)

        self._assert_email_available_for_editor(editor, normalized)

        first_name, last_name = editor_display_names(editor)
        self.client.create_gmail_account(
            email=normalized,
            first_name=first_name,
            last_name=last_name,
            app_password=app_password,
            daily_limit=DEFAULT_ACCOUNT_DAILY_LIMIT,
            enable_slow_ramp=True,
            reply_to=normalized_reply_to or None,
        )
        account = self.client.get_account(normalized)
        return self._upsert_mailbox_from_provider_account(
            editor,
            email=normalized,
            account=account,
            reply_to=normalized_reply_to or None,
        )

    def start_oauth(
        self,
        editor: User,
        *,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        """
        Initialize Instantly Google Workspace OAuth and bind session → editor.
        """
        init = self.client.init_google_oauth()

        if not isinstance(init, dict):
            raise InstantlyAPIError(
                "Unexpected OAuth init response shape",
                response_body=init,
            )

        session_id = init.get("session_id")
        auth_url = init.get("auth_url")
        expires_at = init.get("expires_at")
        if not session_id or not auth_url:
            raise InstantlyAPIError(
                "OAuth init response missing session_id or auth_url",
                response_body=init,
            )

        pending = {
            "editor_id": editor.id,
            "provider": "google",
            "reply_to": normalize_reply_to(reply_to),
        }
        cache.set(
            OAUTH_PENDING_KEY.format(session_id=session_id),
            pending,
            timeout=OAUTH_SESSION_TTL_SECONDS,
        )
        return {
            "session_id": session_id,
            "auth_url": auth_url,
            "expires_at": expires_at,
            "provider": "google",
        }

    def poll_oauth(self, editor: User, session_id: str) -> dict[str, Any]:
        """
        Poll provider OAuth status; on first success, upsert OutreachMailbox.
        """
        if not session_id:
            raise MailboxOAuthSessionNotFoundError("OAuth session not found.")

        done = cache.get(OAUTH_DONE_KEY.format(session_id=session_id))
        if done is not None:
            return self._oauth_payload_from_done(editor, done)

        pending = cache.get(OAUTH_PENDING_KEY.format(session_id=session_id))
        if not isinstance(pending, dict) or pending.get("editor_id") != editor.id:
            raise MailboxOAuthSessionNotFoundError("OAuth session not found.")

        try:
            status_payload = self.client.get_oauth_session_status(session_id)
        except InstantlyNotFoundError:
            return self._finish_oauth(session_id, editor_id=editor.id, status="expired")

        if not isinstance(status_payload, dict):
            raise InstantlyAPIError(
                "Unexpected OAuth status response shape",
                response_body=status_payload,
            )

        status = status_payload.get("status")
        if status == "pending":
            return {"status": "pending"}

        if status == "expired":
            return self._finish_oauth(session_id, editor_id=editor.id, status="expired")

        if status == "error":
            return self._finish_oauth(
                session_id,
                editor_id=editor.id,
                status="error",
                error=status_payload.get("error") or "oauth_error",
                error_description=status_payload.get("error_description") or "",
            )

        if status != "success":
            return self._finish_oauth(
                session_id,
                editor_id=editor.id,
                status="error",
                error="unexpected_status",
                error_description=f"Unexpected OAuth status: {status!r}",
            )

        email = normalize_mailbox_email(
            status_payload.get("email") or status_payload.get("account_id") or ""
        )
        if not email:
            return self._finish_oauth(
                session_id,
                editor_id=editor.id,
                status="error",
                error="missing_email",
                error_description="OAuth success response did not include an email.",
            )

        cached_reply_to = normalize_reply_to(pending.get("reply_to"))

        try:
            self._assert_email_available_for_editor(editor, email)
            account = self.client.get_account(email)
        except (MailboxAlreadyConnectedError, MailboxOwnedByOtherEditorError) as exc:
            conflict = (
                "already_connected"
                if isinstance(exc, MailboxAlreadyConnectedError)
                else "owned_by_other"
            )
            self._finish_oauth(
                session_id,
                editor_id=editor.id,
                status="error",
                error=conflict,
                error_description=str(exc),
                conflict=conflict,
            )
            raise
        except InstantlyAPIError as exc:
            # Provider already consumed the one-shot success status.
            self._finish_oauth(
                session_id,
                editor_id=editor.id,
                status="error",
                error="account_sync_failed",
                error_description=str(exc),
            )
            raise

        mailbox = self._upsert_mailbox_from_provider_account(
            editor,
            email=email,
            account=account,
            reply_to=None,
        )
        # Persist success before optional reply_to so a PATCH failure cannot
        # leave the session stuck as a terminal error after the mailbox exists.
        self._store_oauth_done(
            session_id,
            {
                "status": "success",
                "email": email,
                "mailbox_id": mailbox.id,
                "editor_id": editor.id,
            },
            clear_pending=True,
        )
        if cached_reply_to:
            try:
                updated = self.client.update_account(
                    email, reply_to=cached_reply_to or None
                )
                if isinstance(updated, dict) and "reply_to" in updated:
                    mailbox.reply_to = normalize_reply_to(updated.get("reply_to"))
                else:
                    mailbox.reply_to = cached_reply_to
                mailbox.save(update_fields=["reply_to", "updated_date"])
            except InstantlyAPIError:
                logger.warning(
                    "OAuth mailbox %s created but reply_to sync failed",
                    email,
                    exc_info=True,
                )

        return {"status": "success", "email": email, "mailbox": mailbox}

    def _finish_oauth(
        self,
        session_id: str,
        *,
        editor_id: int,
        status: str,
        error: str | None = None,
        error_description: str | None = None,
        conflict: str | None = None,
    ) -> dict[str, Any]:
        """Cache a terminal OAuth result and return the public poll payload."""
        stored: dict[str, Any] = {"status": status, "editor_id": editor_id}
        if error is not None:
            stored["error"] = error
        if error_description is not None:
            stored["error_description"] = error_description
        if conflict is not None:
            stored["conflict"] = conflict
        self._store_oauth_done(session_id, stored, clear_pending=True)
        if status == "expired":
            return {"status": "expired"}
        return {
            "status": "error",
            "error": error or "oauth_error",
            "error_description": error_description or "",
        }

    def _oauth_payload_from_done(self, editor: User, done: Any) -> dict[str, Any]:
        if not isinstance(done, dict):
            raise MailboxOAuthSessionNotFoundError("OAuth session not found.")

        if done.get("editor_id") is not None and done.get("editor_id") != editor.id:
            raise MailboxOAuthSessionNotFoundError("OAuth session not found.")

        conflict = done.get("conflict")
        if conflict == "already_connected":
            raise MailboxAlreadyConnectedError(
                done.get("error_description")
                or "This email address is already connected."
            )
        if conflict == "owned_by_other":
            raise MailboxOwnedByOtherEditorError(
                done.get("error_description")
                or "This email address is already connected by another editor."
            )

        if done.get("status") == "success":
            mailbox = OutreachMailbox.objects.filter(id=done.get("mailbox_id")).first()
            if mailbox is None or mailbox.editor_id != editor.id:
                raise MailboxOAuthSessionNotFoundError("OAuth session not found.")
            return {
                "status": "success",
                "email": done.get("email") or mailbox.email,
                "mailbox": mailbox,
            }

        if done.get("status") == "expired":
            return {"status": "expired"}
        return {
            "status": "error",
            "error": done.get("error") or "oauth_error",
            "error_description": done.get("error_description") or "",
        }

    def _store_oauth_done(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        clear_pending: bool,
    ) -> None:
        if clear_pending:
            cache.delete(OAUTH_PENDING_KEY.format(session_id=session_id))
        cache.set(
            OAUTH_DONE_KEY.format(session_id=session_id),
            payload,
            timeout=OAUTH_SESSION_TTL_SECONDS,
        )

    def _assert_email_available_for_editor(self, editor: User, email: str) -> None:
        existing = OutreachMailbox.all_objects.filter(email=email).first()
        if existing is not None and existing.editor_id != editor.id:
            raise MailboxOwnedByOtherEditorError(
                "This email address is already connected by another editor."
            )
        if existing is not None and not existing.is_removed:
            raise MailboxAlreadyConnectedError(
                "This email address is already connected."
            )

    def _upsert_mailbox_from_provider_account(
        self,
        editor: User,
        *,
        email: str,
        account: dict[str, Any],
        reply_to: str | None = None,
    ) -> OutreachMailbox:
        """Create or restore a local mailbox from a provider account dict."""
        status = mailbox_status_from_provider(account.get("status"))
        daily_limit = int(account.get("daily_limit") or DEFAULT_ACCOUNT_DAILY_LIMIT)
        provider_code = int(
            account.get("provider_code")
            or OutreachMailbox._meta.get_field("provider_code").default
        )
        synced_reply_to = normalize_reply_to(account.get("reply_to") or reply_to)

        with transaction.atomic():
            existing = OutreachMailbox.all_objects.filter(email=email).first()
            if existing is None:
                return OutreachMailbox.objects.create(
                    editor=editor,
                    email=email,
                    provider_code=provider_code,
                    status=status,
                    daily_limit=daily_limit,
                    reply_to=synced_reply_to,
                )

            mailbox = existing
            mailbox.editor = editor
            mailbox.provider_code = provider_code
            mailbox.status = status
            mailbox.daily_limit = daily_limit
            mailbox.reply_to = synced_reply_to
            mailbox.is_removed = False
            mailbox.is_public = True
            mailbox.is_removed_date = None
            mailbox.save(
                update_fields=[
                    "editor",
                    "provider_code",
                    "status",
                    "daily_limit",
                    "reply_to",
                    "is_removed",
                    "is_public",
                    "is_removed_date",
                    "updated_date",
                ]
            )
            return mailbox

    def detach_mailbox(self, editor: User, mailbox_id: int) -> OutreachMailbox:
        """
        Remove a mailbox from provider campaigns, delete the provider account,
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
            email = mailbox.email
            editor_id = editor.id
            locked_id = mailbox.id

        remaining = list(active_mailboxes_for_editor(editor_id).exclude(id=locked_id))
        self.sync_campaigns_to_active_mailboxes(
            editor_id, mailboxes=remaining, pause_if_empty=True
        )
        self.client.delete_account(email)

        with transaction.atomic():
            mailbox = (
                OutreachMailbox.objects.select_for_update()
                .filter(id=locked_id, editor=editor)
                .first()
            )
            if mailbox is None:
                raise MailboxNotFoundError("Outreach mailbox not found.")
            mailbox.status = OutreachMailbox.Status.DISCONNECTED
            mailbox.save(update_fields=["status", "updated_date"])
            mailbox.delete(soft=True)
            return mailbox

    def list_all_mailboxes_for_moderator(self) -> list[OutreachMailbox]:
        """
        All local outreach mailboxes with live provider warmup + RH send totals.

        Sets ephemeral ``warmup_enabled`` (Instantly) and ``total_sent``
        (count of ``GeneratedEmail`` with ``status=sent`` and matching
        ``sender_account``) for admin serialization.
        """
        mailboxes = list(
            OutreachMailbox.objects.select_related("editor").order_by("-created_date")
        )
        account_by_email = self._provider_accounts_by_email()
        total_sent_by_email = total_sent_by_sender_account(
            [m.email for m in mailboxes]
        )
        for mailbox in mailboxes:
            apply_warmup_attrs(mailbox, account_by_email.get(mailbox.email.lower()))
            mailbox.total_sent = total_sent_by_email.get(mailbox.email.lower(), 0)
        return mailboxes

    def update_daily_limit(self, mailbox_id: int, daily_limit: int) -> OutreachMailbox:
        """
        Set provider account ``daily_limit``.
        """
        return self.update_mailbox(
            actor=None,
            mailbox_id=mailbox_id,
            daily_limit=daily_limit,
            require_moderator_for_daily_limit=False,
        )

    def update_mailbox(
        self,
        actor: User | None,
        mailbox_id: int,
        *,
        reply_to: object = _UNSET,
        daily_limit: object = _UNSET,
        warmup_enabled: object = _UNSET,
        require_moderator_for_daily_limit: bool = True,
    ) -> OutreachMailbox:
        """
        Patch provider account fields.

        ``reply_to``: owner or moderator. ``daily_limit`` / ``warmup_enabled``:
        moderator only (unless ``require_moderator_for_daily_limit`` is False
        for internal daily_limit updates).
        """
        if reply_to is _UNSET and daily_limit is _UNSET and warmup_enabled is _UNSET:
            raise MailboxError("No mailbox fields to update.")

        mailbox = (
            OutreachMailbox.objects.select_related("editor")
            .filter(id=mailbox_id)
            .first()
        )
        if mailbox is None:
            raise MailboxNotFoundError("Outreach mailbox not found.")

        is_moderator = bool(getattr(actor, "moderator", False)) if actor else True
        if actor is not None and mailbox.editor_id != actor.id and not is_moderator:
            raise MailboxNotFoundError("Outreach mailbox not found.")

        patch: dict = {}
        update_fields: list[str] = ["updated_date"]
        local_reply_to: str | None = None

        if reply_to is not _UNSET:
            local_reply_to = normalize_reply_to(reply_to)
            patch["reply_to"] = local_reply_to or None
            mailbox.reply_to = local_reply_to
            update_fields.append("reply_to")

        if daily_limit is not _UNSET:
            if (
                require_moderator_for_daily_limit
                and actor is not None
                and not is_moderator
            ):
                raise MailboxError("Only moderators can update daily_limit.")
            if not isinstance(daily_limit, int):
                raise MailboxError("daily_limit must be an integer.")
            if daily_limit < 1 or daily_limit > MAX_MAILBOX_DAILY_LIMIT:
                raise MailboxError(
                    f"daily_limit must be between 1 and {MAX_MAILBOX_DAILY_LIMIT}."
                )
            patch["daily_limit"] = daily_limit

        if warmup_enabled is not _UNSET:
            if actor is not None and not is_moderator:
                raise MailboxError("Only moderators can update warmup_enabled.")
            if not isinstance(warmup_enabled, bool):
                raise MailboxError("warmup_enabled must be a boolean.")

        if patch:
            account = self.client.update_account(mailbox.email, **patch)
            if "daily_limit" in patch:
                synced = int(account.get("daily_limit") or patch["daily_limit"])
                mailbox.daily_limit = synced
                update_fields.append("daily_limit")
            if reply_to is not _UNSET:
                if isinstance(account, dict) and "reply_to" in account:
                    mailbox.reply_to = normalize_reply_to(account.get("reply_to"))
                else:
                    mailbox.reply_to = local_reply_to or ""
            mailbox.save(update_fields=update_fields)
            if "daily_limit" in patch:
                self.sync_editor_campaign_daily_limits(mailbox.editor_id)

        if warmup_enabled is not _UNSET:
            if warmup_enabled:
                self.client.enable_warmup([mailbox.email])
            else:
                self.client.disable_warmup([mailbox.email])
            try:
                warmup_account = self.client.get_account(mailbox.email)
            except InstantlyNotFoundError:
                warmup_account = None
            apply_warmup_attrs(mailbox, warmup_account)

        return mailbox

    def _provider_accounts_by_email(self) -> dict[str, dict[str, Any]]:
        """Map normalized email → Instantly account dict."""
        by_email: dict[str, dict[str, Any]] = {}
        for account in self.client.iter_accounts():
            email = normalize_mailbox_email(account.get("email") or "")
            if email:
                by_email[email] = account
        return by_email

    def sync_campaigns_to_active_mailboxes(
        self,
        editor_id: int,
        *,
        mailboxes: list[OutreachMailbox] | None = None,
        exclude_mailbox_id: int | None = None,
        pause_if_empty: bool = True,
    ) -> None:
        """
        Push active mailbox emails/limits to the editor's provider campaigns.
        """
        if mailboxes is None:
            qs = active_mailboxes_for_editor(editor_id)
            if exclude_mailbox_id is not None:
                qs = qs.exclude(id=exclude_mailbox_id)
            mailboxes = list(qs)

        email_list = [m.email for m in mailboxes]
        daily_limit = sum(m.daily_limit for m in mailboxes)
        campaigns = list(OutreachCampaign.objects.filter(editor_id=editor_id))

        for campaign in campaigns:
            if not campaign.external_campaign_id:
                if (
                    pause_if_empty
                    and not email_list
                    and campaign.status != OutreachCampaign.Status.NO_ACTIVE_MAILBOXES
                ):
                    campaign.status = OutreachCampaign.Status.NO_ACTIVE_MAILBOXES
                    campaign.save(update_fields=["status", "updated_date"])
                continue

            self.client.update_campaign(
                campaign.external_campaign_id,
                email_list=email_list,
                daily_limit=daily_limit,
            )
            if pause_if_empty and not email_list:
                self.client.pause_campaign(campaign.external_campaign_id)
                if campaign.status != OutreachCampaign.Status.NO_ACTIVE_MAILBOXES:
                    campaign.status = OutreachCampaign.Status.NO_ACTIVE_MAILBOXES
                    campaign.save(update_fields=["status", "updated_date"])

    def sync_editor_campaign_daily_limits(self, editor_id: int) -> None:
        """Push sum of active mailbox daily limits to the editor's campaigns."""
        self.sync_campaigns_to_active_mailboxes(editor_id, pause_if_empty=True)

    def refresh_daily_limits_from_provider(
        self, mailboxes: list[OutreachMailbox]
    ) -> None:
        """Pull provider account daily_limit into the local cache for active rows."""
        for mailbox in mailboxes:
            if mailbox.status != OutreachMailbox.Status.ACTIVE:
                continue
            try:
                account = self.client.get_account(mailbox.email)
            except InstantlyAPIError:
                continue
            if not isinstance(account, dict):
                continue
            raw_limit = account.get("daily_limit")
            try:
                limit = (
                    int(raw_limit)
                    if raw_limit is not None
                    else int(mailbox.daily_limit or DEFAULT_ACCOUNT_DAILY_LIMIT)
                )
            except (TypeError, ValueError):
                continue
            if limit < 1:
                continue
            if limit != mailbox.daily_limit:
                mailbox.daily_limit = limit
                mailbox.save(update_fields=["daily_limit", "updated_date"])

    def get_capacity_summary(self, editor: User) -> dict:
        """
        Editor-level and per-mailbox daily send capacity for settings / send UI.

        Refreshes cached ``daily_limit`` from the provider for active mailboxes,
        then uses provider daily analytics for ``sent_today``. Informational only —
        lead queueing is not blocked when remaining is 0.
        """
        mailboxes = list(
            OutreachMailbox.objects.filter(editor=editor).order_by("-created_date")
        )
        self.refresh_daily_limits_from_provider(mailboxes)
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


def normalize_mailbox_email(email: str) -> str:
    return (email or "").strip().lower()


def normalize_reply_to(email: object) -> str:
    """Normalize Reply-To; empty/None clears the address."""
    if email is None:
        return ""
    return str(email).strip().lower()


def apply_warmup_attrs(
    mailbox: OutreachMailbox, account: dict[str, Any] | None
) -> None:
    """Set ``warmup_enabled`` from Instantly account ``warmup_status`` (1 = on)."""
    status: int | None = None
    if isinstance(account, dict) and account.get("warmup_status") is not None:
        try:
            status = int(account["warmup_status"])
        except (TypeError, ValueError):
            status = None
    mailbox.warmup_enabled = status == WARMUP_STATUS_ACTIVE


def total_sent_by_sender_account(emails: list[str]) -> dict[str, int]:
    """
    Lifetime RH campaign sends per mailbox email.

    Counts ``GeneratedEmail`` rows with ``status=sent`` whose
    ``sender_account`` matches (set from Instantly ``email_sent`` webhooks).
    Warmup / non-RH Instantly traffic is not included.
    """
    normalized = sorted(
        {normalize_mailbox_email(e) for e in emails if normalize_mailbox_email(e)}
    )
    if not normalized:
        return {}
    rows = (
        GeneratedEmail.objects.filter(
            status=GeneratedEmail.Status.SENT,
            sender_account__in=normalized,
        )
        .values("sender_account")
        .annotate(total=Count("id"))
    )
    out: dict[str, int] = {}
    for row in rows:
        key = normalize_mailbox_email(row.get("sender_account") or "")
        if key:
            out[key] = int(row["total"])
    return out


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


def mailbox_status_from_provider(provider_status: object) -> str:
    """
    Map provider account status to ``OutreachMailbox.Status``.

    Active (1) stays active. Paused (2, 3) is excluded from sending by storing
    as error (no local paused status). Negative codes are connection/bounce/
    sending errors.
    """
    try:
        status = int(provider_status)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return OutreachMailbox.Status.ERROR

    if status == ACCOUNT_STATUS_ACTIVE:
        return OutreachMailbox.Status.ACTIVE
    if status in ACCOUNT_STATUS_PAUSED or status in ACCOUNT_STATUS_ERROR:
        return OutreachMailbox.Status.ERROR
    return OutreachMailbox.Status.ERROR
