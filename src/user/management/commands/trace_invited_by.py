from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from user.models import User
import uuid

class Command(BaseCommand):

    def handle(self, *args, **options):
        objects = User.objects.all()
        supports = {}
        for i, user in enumerate(objects):
            print('{} / {}'.format(i, objects.count()))
            if user.invited_by:
                if user.invited_by not in supports:
                    supports[user.invited_by] = 1
                else:
                    supports[user.invited_by] += 1

        sorted_support = {k: v for k, v in sorted(supports.items(), key=lambda item: item[1], reverse=True)}
        print(sorted_support)
