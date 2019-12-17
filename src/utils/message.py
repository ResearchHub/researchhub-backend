from time import sleep
from django.core.mail import send_mail
from django.template.loader import render_to_string
from sentry_sdk import capture_exception

from researchhub.settings import EMAIL_WHITELIST, PRODUCTION
from mailing_list.models import EmailRecipient


def is_valid_email(email):
    # Comment out production conditional for testing
    if not PRODUCTION:
        return email in EMAIL_WHITELIST

    # TODO: Add regex validation
    try:
        recipient, created = EmailRecipient.objects.get_or_create(
            email=email
        )
    except Exception as e:
        print(e)

    return (email in EMAIL_WHITELIST) or (
        (not recipient.do_not_email)
        and (not recipient.is_opted_out)
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

    result = {'success': [], 'failure': [], 'exclude': []}

    # Exclude invalid recipients
    for recipient in recipients:
        if not is_valid_email(recipient):
            result['exclude'].append(recipient)
            recipients.remove(recipient)

    for recipient in recipients:
        # Build email context
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
            result['success'].append(recipient)
        except Exception as e:
            result['failure'].append(recipient)
            capture_exception(e)

        # Stagger sends based on AWS SES limit
        # https://docs.aws.amazon.com/ses/latest/DeveloperGuide/manage-sending-limits.html
        sleep(0.2)

    return result
