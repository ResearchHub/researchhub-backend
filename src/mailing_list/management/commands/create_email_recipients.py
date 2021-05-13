from django.core.management.base import BaseCommand
from user.models import User
from mailing_list.models import EmailRecipient


class Command(BaseCommand):

    def handle(self, *args, **options):
        for user in User.objects.filter(emailrecipient__isnull=True, email__isnull=False):
            EmailRecipient.objects.create(user=user, email=user.email)

