import logging
from dataclasses import dataclass
from time import sleep
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UnsubscribeUrls:
    human: str
    one_click: str


def is_valid_email(email: str) -> bool:
    if settings.TESTING or settings.PRODUCTION:
        return True
    return email in settings.EMAIL_WHITELIST


def _render_body(
    template: str | None, html_template: str | None, context: dict[str, Any]
) -> tuple[str, str | None]:
    """Render plain-text and HTML email bodies from templates."""
    html_body = render_to_string(html_template, context) if html_template else None

    if template:
        plain_body = render_to_string(template, context)
    elif html_body:
        plain_body = strip_tags(html_body).strip()
    else:
        plain_body = ""

    return plain_body, html_body


def _build_headers(list_unsubscribe_url: str | None = None) -> dict[str, str]:
    """Build email headers, adding unsubscribe when applicable."""
    headers: dict[str, str] = {"Precedence": "bulk"}
    if list_unsubscribe_url:
        headers["List-Unsubscribe"] = f"<{list_unsubscribe_url}>"
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    return headers


def deliver_email(
    recipients: str | list[str],
    template: str | None,
    subject: str,
    email_context: dict[str, Any],
    html_template: str | None = None,
    sender: str = f"ResearchHub <{settings.DEFAULT_FROM_EMAIL}>",
    reply_to: str | None = None,
    cc: list[str] | None = None,
    suppressed_emails: set[str] | None = None,
    unsubscribe_urls: dict[str, UnsubscribeUrls] | None = None,
) -> None:
    """Low-level email delivery: render templates, set headers, and send.

    Callers should prefer ``mailing_list.lib.send_email`` which automatically
    looks up suppressed addresses before delegating here.

    Sends are best-effort: a recipient that fails is logged and skipped so one
    bad address cannot abort the rest of the batch.

    Args:
        recipients: Email address string or list of addresses.
        template: Plain-text Django template name
        (e.g. ``"general_email_message.txt"``).
            Pass ``None`` to auto-generate plain text from the HTML.
        subject: Email subject line.
        email_context: Context dict passed to the template(s).
        html_template: HTML Django template name. If ``None``, only the
            plain-text version is sent.
        sender: From address.
        reply_to: Optional reply-to address.
        cc: Optional list of CC addresses.
        suppressed_emails: Optional set of email addresses to exclude.
        unsubscribe_urls: Optional recipient-to-URL-pair mapping for signed
            human-facing links and one-click unsubscribe headers.
    """
    subject = subject.replace("\n", "").replace("\r", "")

    if not isinstance(recipients, list):
        recipients = [recipients]

    if not settings.PRODUCTION:
        subject = "[Staging] " + subject

    for recipient in recipients:
        if not is_valid_email(recipient):
            continue
        if suppressed_emails and recipient in suppressed_emails:
            continue

        context = email_context.copy()
        urls = unsubscribe_urls.get(recipient) if unsubscribe_urls is not None else None
        if urls:
            context["opt_out"] = urls.human

        plain_message, html_message = _render_body(template, html_template, context)
        headers = _build_headers(urls.one_click if urls else None)

        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=plain_message,
                from_email=sender,
                to=[recipient],
                reply_to=[reply_to] if reply_to else None,
                cc=cc,
                headers=headers,
            )
            if html_message:
                msg.attach_alternative(html_message, "text/html")
            msg.send(fail_silently=False)
        except Exception:
            logger.exception("Email send failed to %s", recipient)

        # Stagger sends based on AWS SES limit
        # https://docs.aws.amazon.com/ses/latest/DeveloperGuide/manage-sending-limits.html
        sleep(0.2)
