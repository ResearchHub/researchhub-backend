from django.core.management.base import BaseCommand
from mailing_list.models import EmailRecipient


class Command(BaseCommand):

    def handle(self, *args, **options):
        for email_recipient in EmailRecipient.objects.all():
            email_recipient.save()
