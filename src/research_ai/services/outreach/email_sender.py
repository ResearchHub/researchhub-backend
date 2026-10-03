import logging

from research_ai.services.outreach.gmail_sender import (
    GmailNeedsReauthError,
    GmailNotConnectedError,
    GmailSender,
    OutreachSendResult,
)

logger = logging.getLogger(__name__)


class ExpertFinderOutreachDisabledError(Exception):
    """Raised when expert-finder outreach sending is disabled via killswitch."""


def send_outreach_email(
    user,
    to_email: str,
    subject: str,
    body: str,
    reply_to: list[str] | None = None,
    cc: list[str] | None = None,
    *,
    inject_open_pixel: bool = False,
    open_tracking_token: str | None = None,
) -> OutreachSendResult:
    """
    Send approved outreach via the editor's connected personal Gmail.
    """
    return GmailSender().send(
        user=user,
        to_email=to_email,
        subject=subject,
        body=body,
        reply_to=reply_to,
        cc=cc,
        inject_open_pixel=inject_open_pixel,
        open_tracking_token=open_tracking_token,
    )


def mailbox_connection_error_payload(
    exc: GmailNotConnectedError | GmailNeedsReauthError,
) -> dict[str, str]:
    """JSON body for 409 Gmail connection errors."""
    return {"detail": exc.detail, "code": exc.code}
