from django.core.management.base import BaseCommand
from user.models import User
from mailing_list.models import EmailRecipient


class Command(BaseCommand):

    def handle(self, *args, **options):
        EmailRecipient.objects.all().update(is_subscribed=True)
