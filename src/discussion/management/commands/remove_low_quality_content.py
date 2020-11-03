from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from django.db.models.functions import Length

from user.models import User
from discussion.models import Thread
import uuid

class Command(BaseCommand):

    def handle(self, *args, **options):
        low_threads = Thread.objects.annotate(text_len=Length('plain_text')).filter(text_len__lte=10)
        for i, thread in enumerate(low_threads):
            thread.is_removed = True
            thread.save()
