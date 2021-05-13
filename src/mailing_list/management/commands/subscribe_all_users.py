from django.core.management.base import BaseCommand
# from user.models import User
# from mailing_list.models import EmailRecipient


class Command(BaseCommand):

    def handle(self, *args, **options):
        # TODO: Alter this because we have removed the is_subscribed field
        # EmailRecipient.objects.all().update(is_subscribed=True)
        pass
