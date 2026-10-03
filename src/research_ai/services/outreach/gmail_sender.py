"""Send Expert Finder outreach via the Gmail API."""

from __future__ import annotations

import base64
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.utils import timezone

from research_ai.models.outreach_mailbox_connection import OutreachMailboxConnection
from research_ai.services.outreach.gmail_oauth import (
    GOOGLE_TOKEN_URL,
    REQUEST_TIMEOUT,
    get_google_oauth_credentials,
)

logger = logging.getLogger(__name__)

GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
OPEN_TRACKING_PATH = "/api/research_ai/expert-finder/emails/t/{token}/"
PIXEL_IMG = (
    '<img src="{url}" width="1" height="1" alt="" '
    'style="display:none;border:0;width:1px;height:1px;" />'
)


class GmailNotConnectedError(Exception):
    """No active personal Gmail mailbox connection for this user."""

    code = "gmail_not_connected"
    detail = "Gmail not connected"


class GmailNeedsReauthError(Exception):
    """Mailbox connection requires the editor to reconnect Gmail."""

    code = "gmail_needs_reauth"
    detail = "Gmail needs reauthorization"


class GmailSendError(Exception):
    """Gmail API send or token refresh failed."""


@dataclass(frozen=True)
class OutreachSendResult:
    """Result of a successful Gmail send."""

    message_id: str
    thread_id: str = ""
    open_tracking_token: str = ""


def get_active_outreach_mailbox(user) -> OutreachMailboxConnection:
    """Return the user's active mailbox or raise a connection error."""
    try:
        connection = user.outreach_mailbox_connection
    except OutreachMailboxConnection.DoesNotExist as exc:
        raise GmailNotConnectedError from exc

    if connection.status == OutreachMailboxConnection.Status.NEEDS_REAUTH:
        raise GmailNeedsReauthError
    if connection.status != OutreachMailboxConnection.Status.ACTIVE:
        raise GmailNotConnectedError
    return connection


def new_open_tracking_token() -> str:
    """Generate an opaque token for the open-tracking pixel."""
    return secrets.token_urlsafe(32)


def open_tracking_pixel_url(token: str) -> str:
    """Absolute URL for the open-tracking pixel endpoint."""
    base = getattr(settings, "BASE_BACKEND_URL", "http://localhost:8000").rstrip("/")
    return f"{base}{OPEN_TRACKING_PATH.format(token=token)}"


def inject_open_tracking_pixel(html_body: str, token: str) -> str:
    """Append a 1x1 tracking pixel; does not mutate stored drafts."""
    pixel = PIXEL_IMG.format(url=open_tracking_pixel_url(token))
    body = html_body or ""
    lower = body.lower()
    idx = lower.rfind("</body>")
    if idx != -1:
        return f"{body[:idx]}{pixel}{body[idx:]}"
    return f"{body}{pixel}"


def _html_to_plain_text(html: str) -> str:
    """Best-effort plain-text alternative for multipart MIME."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for element in soup(["head", "script", "style", "title"]):
        element.decompose()
    return " ".join(soup.get_text().split()).strip() or "(No content)"


def build_raw_gmail_message(
    *,
    from_email: str,
    to_email: str,
    subject: str,
    html_body: str,
    reply_to: list[str] | None = None,
    cc: list[str] | None = None,
) -> str:
    """Build a base64url-encoded RFC 2822 message for Gmail messages.send."""
    subject = (subject or "").replace("\n", "").replace("\r", "")

    message = MIMEMultipart("alternative")
    message["To"] = to_email
    message["From"] = from_email
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = ", ".join(reply_to)
    if cc:
        message["Cc"] = ", ".join(cc)

    plain = _html_to_plain_text(html_body)
    message.attach(MIMEText(plain, "plain", "utf-8"))
    message.attach(MIMEText(html_body or "", "html", "utf-8"))
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


class GmailApiClient:
    """Thin HTTP client for Gmail token refresh and messages.send."""

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests

    def refresh_access_token(
        self,
        *,
        refresh_token: str,
        client_id: str,
        client_secret: str,
    ) -> dict[str, Any]:
        response = self.session.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code >= 400:
            payload = _safe_json(response)
            error = (payload or {}).get("error") or ""
            if error == "invalid_grant":
                raise GmailNeedsReauthError
            raise GmailSendError(
                f"Token refresh failed: {error or response.status_code}"
            )
        return response.json()

    def send_message(self, *, access_token: str, raw: str) -> dict[str, Any]:
        response = self.session.post(
            GMAIL_SEND_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"raw": raw},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code >= 400:
            payload = _safe_json(response)
            error = (payload or {}).get("error") or {}
            status_code = error.get("code") if isinstance(error, dict) else None
            message = (
                error.get("message") if isinstance(error, dict) else None
            ) or response.text
            # OAuth revoked / expired access often surfaces as 401.
            if response.status_code == 401 or status_code == 401:
                raise GmailNeedsReauthError
            raise GmailSendError(f"Gmail send failed: {message}")
        return response.json()


class GmailSender:
    """Refresh mailbox tokens and send outreach via Gmail API."""

    def __init__(self, client: GmailApiClient | None = None):
        self.client = client or GmailApiClient()

    def send(
        self,
        *,
        user,
        to_email: str,
        subject: str,
        body: str,
        reply_to: list[str] | None = None,
        cc: list[str] | None = None,
        inject_open_pixel: bool = False,
        open_tracking_token: str | None = None,
    ) -> OutreachSendResult:
        """
        Send one message from the user's connected personal Gmail
        """
        if not settings.EXPERT_FINDER_OUTREACH_ENABLED:
            # Lazy import avoids circular dependency with email_sender.
            from research_ai.services.outreach.email_sender import (
                ExpertFinderOutreachDisabledError,
            )

            logger.warning(
                "Expert finder outreach disabled; refusing Gmail send to %s",
                to_email,
            )
            raise ExpertFinderOutreachDisabledError(
                "Expert finder outreach is temporarily disabled."
            )

        connection = get_active_outreach_mailbox(user)
        try:
            access_token = self._ensure_access_token(connection)
            html_body = body or ""
            token = ""
            if inject_open_pixel:
                token = open_tracking_token or new_open_tracking_token()
                html_body = inject_open_tracking_pixel(html_body, token)

            raw = build_raw_gmail_message(
                from_email=connection.email,
                to_email=to_email,
                subject=subject,
                html_body=html_body,
                reply_to=reply_to,
                cc=cc,
            )
            payload = self.client.send_message(access_token=access_token, raw=raw)
        except GmailNeedsReauthError:
            self._mark_needs_reauth(
                connection, "Gmail authorization revoked or expired"
            )
            raise

        message_id = payload.get("id") or ""
        if not message_id:
            raise GmailSendError("Gmail send response missing message id")
        return OutreachSendResult(
            message_id=message_id,
            thread_id=payload.get("threadId") or "",
            open_tracking_token=token if inject_open_pixel else "",
        )

    def _ensure_access_token(self, connection: OutreachMailboxConnection) -> str:
        if connection.access_token and not connection.is_access_token_expired():
            return connection.access_token
        if not connection.refresh_token:
            raise GmailNeedsReauthError

        client_id, client_secret = get_google_oauth_credentials()
        token_data = self.client.refresh_access_token(
            refresh_token=connection.refresh_token,
            client_id=client_id,
            client_secret=client_secret,
        )

        access_token = token_data.get("access_token") or ""
        if not access_token:
            raise GmailSendError("Token refresh missing access_token")

        expires_in = int(token_data.get("expires_in") or 0)
        connection.access_token = access_token
        connection.access_token_expires_at = (
            timezone.now() + timedelta(seconds=expires_in) if expires_in else None
        )
        connection.last_error = ""
        connection.save(
            update_fields=[
                "access_token",
                "access_token_expires_at",
                "last_error",
                "updated_date",
            ]
        )
        return access_token

    @staticmethod
    def _mark_needs_reauth(connection: OutreachMailboxConnection, error: str) -> None:
        connection.status = OutreachMailboxConnection.Status.NEEDS_REAUTH
        connection.last_error = error
        connection.save(
            update_fields=["status", "last_error", "updated_date"],
        )
        logger.warning(
            "Gmail mailbox needs reauth user_id=%s email=%s: %s",
            connection.user_id,
            connection.email,
            error,
        )


def _safe_json(response: requests.Response) -> dict[str, Any] | None:
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
