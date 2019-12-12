from researchhub.settings import PRODUCTION, EMAIL_WHITELIST

from django.template.loader import render_to_string
from django.core.mail import send_mail
from sentry_sdk import capture_exception

from user.models import EmailPreference

from time import sleep

def is_valid_email(email):
    preferences = EmailPreference.objects.filter(email=email)
    opt_out = False
    for preference in preferences:
        opt_out = preference.opt_out
    send = PRODUCTION or 'quantfive.org' in email or email in EMAIL_WHITELIST
    return send and not opt_out

def send_email_message(recipients, message, subject, emailContext, html_message=None):
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