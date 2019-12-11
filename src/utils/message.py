from time import sleep
from django.core.mail import send_mail
from django.template.loader import render_to_string
from sentry_sdk import capture_exception

from researchhub.settings import EMAIL_WHITELIST, PRODUCTION
from user.models import EmailPreference


def is_valid_email(email):
    if not PRODUCTION:
        return email in EMAIL_WHITELIST

    preference = EmailPreference.objects.get(email=email)
    return (email in EMAIL_WHITELIST) or (
        (not preference.opt_out)
        and (not preference.bounced)
    )


def send_email_message(
    recipients,
    message,
    subject,
    emailContext,
    html_message=None
):
    if not isinstance(recipients, list):
        recipients = [recipients]

    recipients = [r for r in recipients if is_valid_email(r)]
    success = 1
    for recipient in recipients:
        customContext = emailContext
        if 'opt_out' in emailContext.keys():
            customContext['opt_out'] += '?email={}'.format(recipient)

        msg_plain = render_to_string(message, customContext)
        msg_html = render_to_string(html_message, customContext)
        send_to = [recipient]
        try:
            send_mail(
                subject,
                msg_plain,
                'noreply@researchhub.com',
                send_to,
                html_message=msg_html,
                fail_silently=False,
            )
        except Exception as e:
            capture_exception(e)
            success = 0

        sleep(1)
    return success
