import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def _send_to_recipient(to, subject, plain_body, from_email, html_body):
    try:
        send_mail(
            subject,
            plain_body,
            from_email,
            [to],
            fail_silently=False,
            html_message=html_body,
        )
    except Exception as e:
        logger.exception("Send email failed to %s: %s", to, e)
        raise


def send_plain_email(
    to_emails,
    subject,
    body,
    reply_to=None,
    cc=None,
    from_email=None,
):
    """
    Send an email with optional HTML body. Normalizes subject, adds staging prefix
    when not production, and supports reply_to/cc via EmailMultiAlternatives.
    """
    subject = (subject or "").replace("\n", "").replace("\r", "")
    if not settings.PRODUCTION:
        subject = "[Staging] " + subject
    if from_email is None:
        from_email = f"ResearchHub <{settings.DEFAULT_FROM_EMAIL}>"
    to_list = to_emails if isinstance(to_emails, list) else [to_emails]
    html_body = body or ""
    plain_body = strip_tags(html_body).strip() or "(No content)"

    if reply_to or cc:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=plain_body,
            from_email=from_email,
            to=to_list,
            reply_to=[reply_to] if reply_to else None,
            cc=cc or None,
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
    else:
        for to in to_list:
            _send_to_recipient(to, subject, plain_body, from_email, html_body)
