from researchhub.settings import PRODUCTION, EMAIL_WHITELIST

from django.core.mail import send_mail
from sentry_sdk import capture_exception

def is_valid_email(email):
    return PRODUCTION or 'quantfive.org' in email or email in EMAIL_WHITELIST

def send_email_message(recipients, message, subject, html_message=None):
    if not isinstance(recipients, list):
        recipients = [recipients]

    recipients = [r for r in recipients if is_valid_email(r)]

    try:
        return send_mail(
            subject,
            message,
            'noreply@researchhub.com',
            recipients,
            html_message=html_message,
            fail_silently=False,
        )
    except Exception as e:
        print(e)
        # capture_exception(e)