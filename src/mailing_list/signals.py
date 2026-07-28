from django.dispatch import receiver
from django_ses.signals import bounce_received, complaint_received

from mailing_list.services.ses_event_service import SesEventService


@receiver(bounce_received, dispatch_uid="mailing_list_ses_bounce")
def handle_ses_bounce_event(sender, bounce_obj, **kwargs):
    """
    Mark addresses as bounced when SES reports a permanent bounce.
    """
    SesEventService().handle_bounce(bounce_obj)


@receiver(complaint_received, dispatch_uid="mailing_list_ses_complaint")
def handle_ses_complaint_event(sender, complaint_obj, **kwargs):
    """
    Mark addresses as opted-out when SES reports a complaint (spam).
    """
    SesEventService().handle_complaint(complaint_obj)
