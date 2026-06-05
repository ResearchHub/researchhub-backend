from typing import Any

from django.conf import settings

from researchhub.settings import (
    ASSETS_BASE_URL,
    BASE_FRONTEND_URL,
)
from utils.message import deliver_email


class NotificationFrequencies:
    IMMEDIATE = 0
    DAILY = 1440
    THREE_HOUR = 180
    WEEKLY = 10080


base_email_context = {
    "assets_base_url": ASSETS_BASE_URL,
    "opt_out": BASE_FRONTEND_URL + "/email/opt-out/",
    "update_subscription": BASE_FRONTEND_URL + "/user/settings/",
}


def send_email(
    recipients: str | list[str],
    template: str | None,
    subject: str,
    email_context: dict[str, Any],
    html_template: str | None = None,
    sender: str = f"ResearchHub <{settings.DEFAULT_FROM_EMAIL}>",
    reply_to: str | None = None,
    cc: list[str] | None = None,
) -> dict[str, list[str]]:
    """Send an email, automatically suppressing bounced/opted-out addresses.

    This is the standard entry point for sending emails. It looks up
    suppressed addresses via ``EmailRecipient`` and delegates delivery
    to ``utils.message.deliver_email``.
    """
    # Avoid circular import
    from mailing_list.models import EmailRecipient

    if not isinstance(recipients, list):
        recipients = [recipients]

    suppressed = EmailRecipient.get_suppressed_emails(recipients)

    return deliver_email(
        recipients=recipients,
        template=template,
        subject=subject,
        email_context=email_context,
        html_template=html_template,
        sender=sender,
        reply_to=reply_to,
        cc=cc,
        suppressed_emails=suppressed,
    )
