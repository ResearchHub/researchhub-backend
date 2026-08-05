import logging
from time import sleep
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from mailing_list.models import EmailOptOut
from mailing_list.services import EmailSubscriptionService

logger = logging.getLogger(__name__)

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
) -> None:
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
    _send(
        recipients=recipients,
        template=template,
        subject=subject,
        email_context=email_context,
        html_template=html_template,
        sender=sender,
        reply_to=reply_to,
        cc=cc,
        unsubscribable=True,
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
) -> None:
    """
    Send transactional email that ignores notification opt-outs.

    Transactional emails can include email confirmation, password reset, and others.
    Opting out of other notifications must not lock someone out of their own account.
    """
    _send(
        recipients=recipients,
        template=template,
        subject=subject,
        email_context=email_context,
        html_template=html_template,
        sender=sender,
        reply_to=reply_to,
        cc=cc,
        unsubscribable=False,
    )


def _send(
    recipients: str | list[str],
    template: str | None,
    subject: str,
    email_context: dict[str, Any],
    html_template: str | None,
    sender: str,
    reply_to: str | None,
    cc: list[str] | None,
    *,
    unsubscribable: bool,
) -> None:
    """
    Render and send one message per recipient.

    Sends are best-effort: a recipient that fails is logged and skipped so one
    bad address cannot abort the rest of the batch.
    """
    subject = subject.replace("\n", "").replace("\r", "")

    if not isinstance(recipients, list):
        recipients = [recipients]

    if not settings.PRODUCTION:
        subject = "[Staging] " + subject

    opted_out = EmailOptOut.filter_opted_out(recipients) if unsubscribable else set()
    subscriptions = EmailSubscriptionService()

    for recipient in recipients:
        if recipient in opted_out or not _is_allowed_recipient(recipient):
            continue

        context = {"assets_base_url": settings.ASSETS_BASE_URL, **email_context}
        headers: dict[str, str] = {}

        if unsubscribable:
            try:
                opt_out_url = subscriptions.generate_unsubscribe_url(recipient)
                one_click_url = subscriptions.generate_list_unsubscribe_url(recipient)
            except ValidationError:
                # If it's not a valid address, there is nothing to unsubscribe
                logger.warning(
                    "Skipping unsubscribe links for invalid recipient",
                    extra={"recipient": recipient},
                )
            else:
                context["opt_out"] = opt_out_url
                headers["Precedence"] = "bulk"
                headers["List-Unsubscribe"] = f"<{one_click_url}>"
                headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        plain_body, html_body = _render_body(template, html_template, context)

        try:
            message = EmailMultiAlternatives(
                subject=subject,
                body=plain_body,
                from_email=sender,
                to=[recipient],
                reply_to=[reply_to] if reply_to else None,
                cc=cc,
                headers=headers,
            )
            if html_body:
                message.attach_alternative(html_body, "text/html")
            message.send(fail_silently=False)
        except Exception:
            logger.exception("Email send failed to %s", recipient)

        # Stagger sends based on AWS SES limit
        # https://docs.aws.amazon.com/ses/latest/DeveloperGuide/manage-sending-limits.html
        sleep(0.2)


def _render_body(
    template: str | None, html_template: str | None, context: dict[str, Any]
) -> tuple[str, str | None]:
    """
    Render the plain-text and HTML bodies, deriving the text from the HTML when
    no text template is given.
    """
    html_body = render_to_string(html_template, context) if html_template else None

    if template:
        plain_body = render_to_string(template, context)
    elif html_body:
        plain_body = strip_tags(html_body).strip()
    else:
        plain_body = ""

    return plain_body, html_body


def _is_allowed_recipient(email: str) -> bool:
    """
    Return whether the email is allowed for sending in the current environment.

    An entry starting with `@` whitelists an entire domain, so `@researchhub.com`
    allows every recipient at that domain.
    """
    if settings.TESTING or settings.PRODUCTION:
        return True

    email = email.strip().lower()
    _, _, domain = email.rpartition("@")

    return any(
        entry == email or (entry.startswith("@") and entry[1:] == domain)
        for entry in (e.strip().lower() for e in settings.EMAIL_WHITELIST)
    )
