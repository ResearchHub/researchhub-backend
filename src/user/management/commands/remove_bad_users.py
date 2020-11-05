from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from user.models import User
import uuid
from user.tasks import handle_spam_user_task

class Command(BaseCommand):

    def handle(self, *args, **options):
        objects = User.objects.filter(probable_spammer=True)
        count = objects.count()
        for i, user in enumerate(objects):
            print('{} / {}'.format(i, count))
            handle_spam_user_task(user.id)
            user.papers.update(is_removed=True)
