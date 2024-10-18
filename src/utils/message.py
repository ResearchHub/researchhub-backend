from time import sleep

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from sentry_sdk import capture_exception


def is_valid_email(email):
    if settings.TESTING or settings.PRODUCTION:
        return True

    return email in settings.EMAIL_WHITELIST


def send_email_message(
    recipients,
    template,
    subject,
    email_context,
    html_template=None,
    sender=f"ResearchHub <{settings.DEFAULT_FROM_EMAIL}>",
):
    """Emails `message` to `recipients` and returns a dict with results in the
    following form:
    ```
    {
        'success':[recipient_email_address, ...],
        'failure':[recipient_email_address, ...],
        'exclude':[recipient_email_address, ...]
    }
    ```

    Args:
        recipients (str|list) - Email addresses to send to
        template (str) - Template name
        subject (str) - Email subject
        email_context (dict) - Data to send to template
        html_template (:str:) - Optional html template name
    """
    subject = subject.replace("\n", "")
    subject = subject.replace("\r", "")

    if not isinstance(recipients, list):
        recipients = [recipients]

    if not settings.PRODUCTION:
        subject = "[Staging] " + subject

    result = {"success": [], "failure": [], "exclude": []}

    # Exclude invalid recipients
    for recipient in recipients:
        if not is_valid_email(recipient):
            result["exclude"].append(recipient)
            recipients.remove(recipient)
            print("EMAIL NOT IN WHITELIST")

    for recipient in recipients:
        # Build email context
        customContext = email_context
        if "opt_out" in email_context.keys():
            customContext["opt_out"] += "?email={}".format(recipient)

        message = render_to_string(template, customContext)
        html_message = render_to_string(html_template, customContext)
        send_to = [recipient]

        try:
            send_mail(
                subject,
                message,
                sender,
                send_to,
                html_message=html_message,
                fail_silently=False,
            )
            result["success"].append(recipient)
        except Exception as e:
            print(e)
            result["failure"].append(recipient)
            capture_exception(e)

        # Stagger sends based on AWS SES limit
        # https://docs.aws.amazon.com/ses/latest/DeveloperGuide/manage-sending-limits.html
        sleep(0.2)

    return result
