import logging

from django.conf import settings

from mailing_list.services import EmailService

logger = logging.getLogger(__name__)


class ExpertFinderOutreachDisabledError(Exception):
    """Raised when expert-finder outreach sending is disabled via killswitch."""


def send_outreach_email(
    to_email: str,
    subject: str,
    body: str,
    reply_to: list[str] | None = None,
    cc: list[str] | None = None,
    from_email: str | None = None,
) -> str | None:
    """Send approved outreach; return None if skipped or its ID (possibly empty)."""
    if not settings.EXPERT_FINDER_OUTREACH_ENABLED:
        logger.warning(
            "Expert finder outreach disabled; refusing send to %s",
            to_email,
        )
        raise ExpertFinderOutreachDisabledError(
            "Expert finder outreach is temporarily disabled."
        )

    return EmailService().send_html_email(
        to_email,
        subject,
        body,
        sender=from_email,
        reply_to=reply_to,
        cc=cc,
    )
