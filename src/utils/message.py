import logging
from time import sleep
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from sentry_sdk import capture_exception

logger = logging.getLogger(__name__)


def is_valid_email(email: str) -> bool:
    if settings.TESTING or settings.PRODUCTION:
        return True
    return email in settings.EMAIL_WHITELIST


def _filter_recipients(
    recipients: list[str],
    suppressed_emails: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Partition recipients into sendable and excluded lists.

    Args:
        recipients: List of email addresses to filter.
        suppressed_emails: Optional pre-computed set of emails to exclude.

    Returns:
        (sendable, excluded) – two lists of email addresses.
    """
    sendable = [r for r in recipients if is_valid_email(r)]
    excluded = list(set(recipients) - set(sendable))

    if sendable and suppressed_emails:
        excluded.extend(suppressed_emails & set(sendable))
        sendable = [r for r in sendable if r not in suppressed_emails]

    return sendable, excluded


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


def _build_headers(opt_out_url: str | None = None) -> dict[str, str]:
    """Build email headers, adding unsubscribe when applicable."""
    headers: dict[str, str] = {"Precedence": "bulk"}
    if opt_out_url:
        headers["List-Unsubscribe"] = (
            f"<mailto:{settings.DEFAULT_FROM_EMAIL}?subject=unsubscribe>, "
            f"<{opt_out_url}>"
        )
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
) -> dict[str, list[str]]:
    """Low-level email delivery: render templates, set headers, and send.

    Callers should prefer ``mailing_list.lib.send_email`` which automatically
    looks up suppressed addresses before delegating here.

    Args:
        recipients: Email address string or list of addresses.
        template: Plain-text Django template name (e.g. ``"general_email_message.txt"``).
            Pass ``None`` to auto-generate plain text from the HTML.
        subject: Email subject line.
        email_context: Context dict passed to the template(s).
        html_template: HTML Django template name. If ``None``, only the
            plain-text version is sent.
        sender: From address.
        reply_to: Optional reply-to address.
        cc: Optional list of CC addresses.
        suppressed_emails: Optional set of email addresses to exclude.

    Returns:
        ``{"success": [...], "failure": [...], "exclude": [...]}``.
    """
    subject = subject.replace("\n", "").replace("\r", "")

    if not isinstance(recipients, list):
        recipients = [recipients]

    if not settings.PRODUCTION:
        subject = "[Staging] " + subject

    sendable, excluded = _filter_recipients(recipients, suppressed_emails)
    result = {"success": [], "failure": [], "exclude": excluded}

    if not sendable:
        return result

    for recipient in sendable:
        context = email_context.copy()
        opt_out_url = context.get("opt_out")
        if opt_out_url:
            opt_out_url += f"?email={recipient}"
            context["opt_out"] = opt_out_url

        plain_message, html_message = _render_body(template, html_template, context)
        headers = _build_headers(opt_out_url)

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
            result["success"].append(recipient)
        except Exception as e:
            logger.exception("Email send failed to %s", recipient)
            result["failure"].append(recipient)
            capture_exception(e)

        # Stagger sends based on AWS SES limit
        # https://docs.aws.amazon.com/ses/latest/DeveloperGuide/manage-sending-limits.html
        sleep(0.2)

    return result
