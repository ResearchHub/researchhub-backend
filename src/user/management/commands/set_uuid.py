from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from user.models import User
import uuid

class Command(BaseCommand):

    def handle(self, *args, **options):
        objects = User.objects.all()
        for user in objects:
            user.referral_code = uuid.uuid4()
            user.save()
