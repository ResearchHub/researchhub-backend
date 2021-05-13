from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from user.models import Action
import uuid

class Command(BaseCommand):

    def handle(self, *args, **options):
        models = [
            'bulletpoint',
            'thread',
            'paper',
            'comment',
            'reply',
            'summary'
        ]
        objects = Action.objects.filter(
            user__isnull=False,
            content_type__model__in=models,
            display=True,
        )
        count = objects.count()
        for i, action in enumerate(objects):
            print('{} / {}'.format(i, count))
            if action.item.is_removed:
                action.display = False
                action.save()
