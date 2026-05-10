from django.core.management.base import BaseCommand

from mailing_list.models import EmailRecipient
from user.models import User


class Command(BaseCommand):

    def handle(self, *args, **options):
        for user in User.objects.filter(emailrecipient__isnull=True, email__isnull=False):
            EmailRecipient.objects.create(user=user, email=user.email)

