import logging

logger = logging.getLogger(__name__)


class ExpertFinderOutreachDisabledError(Exception):
    """Raised when expert-finder SES outreach sending is disabled."""


def send_outreach_email(
    to_email: str,
    subject: str,
    body: str,
    reply_to: list[str] | None = None,
    cc: list[str] | None = None,
    from_email: str | None = None,
) -> str | None:
    """
    Legacy SES outreach send.

    Expert Finder outreach now uses Instantly campaigns. New sends must go
    through ``OutreachCampaignService.send_to_experts``; this path always
    refuses so SES is not used for new outreach.
    """
    _ = (subject, body, reply_to, cc, from_email)
    logger.warning(
        "Expert finder SES outreach disabled; refusing send to %s",
        to_email,
    )
    raise ExpertFinderOutreachDisabledError(
        "Expert finder outreach via SES is disabled; use Instantly campaigns."
    )
