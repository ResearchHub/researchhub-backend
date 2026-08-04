import logging
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError

from mailing_list.models import EmailOptOut
from mailing_list.services import EmailSubscriptionService
from researchhub.settings import (
    ASSETS_BASE_URL,
    BASE_FRONTEND_URL,
)
from utils.message import UnsubscribeUrls, deliver_email

logger = logging.getLogger(__name__)

base_email_context = {
    "assets_base_url": ASSETS_BASE_URL,
    "update_subscription": BASE_FRONTEND_URL + "/user/settings/",
}

DEFAULT_SENDER = f"ResearchHub <{settings.DEFAULT_FROM_EMAIL}>"


def send_email(
    recipients: str | list[str],
    template: str | None,
    subject: str,
    email_context: dict[str, Any],
    html_template: str | None = None,
    sender: str = DEFAULT_SENDER,
    reply_to: str | None = None,
    cc: list[str] | None = None,
) -> dict[str, list[str]]:
    """
    Send notification email, skipping addresses that have opted out.

    This is the standard entry point, and the right default for anything the
    recipient could reasonably not want. Recipients get a signed unsubscribe
    link in the body and a matching `List-Unsubscribe` header. Use
    `send_transactional_email` for mail they must receive regardless of their
    preferences.

    Undeliverable and complained-about addresses are handled separately by the
    SES backend's blacklist, which applies to both functions.
    """
    if not isinstance(recipients, list):
        recipients = [recipients]

    suppressed = EmailOptOut.filter_opted_out(recipients)

    service = EmailSubscriptionService()
    unsubscribe_urls: dict[str, UnsubscribeUrls] = {}
    for recipient in recipients:
        if recipient in suppressed:
            continue
        try:
            unsubscribe_urls[recipient] = UnsubscribeUrls(
                human=service.generate_unsubscribe_url(recipient),
                one_click=service.generate_list_unsubscribe_url(recipient),
            )
        except ValidationError:
            # If it's not a valid address, there is nothing to unsubscribe
            logger.warning(
                "Skipping unsubscribe links for invalid recipient",
                extra={"recipient": recipient},
            )

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
        unsubscribe_urls=unsubscribe_urls,
    )


def send_transactional_email(
    recipients: str | list[str],
    template: str | None,
    subject: str,
    email_context: dict[str, Any],
    html_template: str | None = None,
    sender: str = DEFAULT_SENDER,
    reply_to: str | None = None,
    cc: list[str] | None = None,
) -> dict[str, list[str]]:
    """
    Send transactional email that ignores notification opt-outs.

    Transactional emails can include email confirmation, password reset, and others.
    Opting out of other notifications must not lock someone out of their own account.
    """
    return deliver_email(
        recipients=recipients,
        template=template,
        subject=subject,
        email_context=email_context,
        html_template=html_template,
        sender=sender,
        reply_to=reply_to,
        cc=cc,
    )
