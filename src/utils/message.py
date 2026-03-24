import logging
from time import sleep

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from sentry_sdk import capture_exception

logger = logging.getLogger(__name__)


def is_valid_email(email):
    if settings.TESTING or settings.PRODUCTION:
        return True
    return email in settings.EMAIL_WHITELIST


def get_suppressed_emails(emails):
    """Return the subset of *emails* that should not receive mail.

    An address is suppressed when its ``EmailRecipient`` record has
    ``do_not_email=True`` (bounced / complained) or ``is_opted_out=True``.
    """
    from mailing_list.models import EmailRecipient

    return set(
        EmailRecipient.objects.filter(
            email__in=emails,
        )
        .filter(Q(do_not_email=True) | Q(is_opted_out=True))
        .values_list("email", flat=True)
    )


def send_email_message(
    recipients,
    template,
    subject,
    email_context,
    html_template=None,
    sender=f"ResearchHub <{settings.DEFAULT_FROM_EMAIL}>",
    is_transactional=False,
    reply_to=None,
    cc=None,
):
    """Send a branded email to one or more recipients.

    Args:
        recipients: Email address string or list of addresses.
        template: Plain-text Django template name (e.g. ``"general_email_message.txt"``).
            Pass ``None`` to auto-generate plain text from the HTML.
        subject: Email subject line.
        email_context: Context dict passed to the template(s).
        html_template: HTML Django template name. If ``None``, only the
            plain-text version is sent.
        sender: From address.
        is_transactional: If ``True``, skip suppression checks and set
            ``X-Auto-Response-Suppress`` header (for password resets, etc.).
        reply_to: Optional reply-to address.
        cc: Optional list of CC addresses.

    Returns:
        ``{"success": [...], "failure": [...], "exclude": [...]}``.
    """
    subject = subject.replace("\n", "").replace("\r", "")

    if not isinstance(recipients, list):
        recipients = [recipients]

    if not settings.PRODUCTION:
        subject = "[Staging] " + subject

    result = {"success": [], "failure": [], "exclude": []}

    if is_transactional:
        sendable = list(recipients)
    else:
        sendable = [r for r in recipients if is_valid_email(r)]
        result["exclude"].extend(set(recipients) - set(sendable))

    if not is_transactional and sendable:
        suppressed = get_suppressed_emails(sendable)
        result["exclude"].extend(suppressed)
        sendable = [r for r in sendable if r not in suppressed]

    if not sendable:
        return result

    base_headers = {}
    if is_transactional:
        base_headers["X-Auto-Response-Suppress"] = "All"
    else:
        base_headers["Precedence"] = "bulk"

    for recipient in sendable:
        context = email_context.copy()
        if "opt_out" in context:
            context["opt_out"] += f"?email={recipient}"

        html_message = (
            render_to_string(html_template, context) if html_template else None
        )

        if template:
            plain_message = render_to_string(template, context)
        elif html_message:
            plain_message = strip_tags(html_message).strip()
        else:
            plain_message = ""

        headers = {**base_headers}
        unsub_url = context.get("opt_out")
        if unsub_url and not is_transactional:
            headers["List-Unsubscribe"] = (
                f"<mailto:{settings.DEFAULT_FROM_EMAIL}?subject=unsubscribe>, "
                f"<{unsub_url}>"
            )
            headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

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
