from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from django.db.models.functions import Length

from user.models import User
from discussion.models import Thread
import uuid

from utils.siftscience import decisions_api, events_api

class Command(BaseCommand):

    def handle(self, *args, **options):
        low_threads = Thread.objects.annotate(text_len=Length('plain_text')).filter(text_len__lte=25, is_removed=False)
        thread_count = low_threads.count()
        for i, thread in enumerate(low_threads):
            print('{} / {}'.format(i, thread_count))
            thread.is_removed = True
            content_id = f'{type(thread).__name__}_{thread.id}'

            if not thread.created_by:
                continue
            try:
                decisions_api.apply_bad_content_decision(thread.created_by, content_id)
                events_api.track_flag_content(
                    thread.created_by,
                    content_id,
                    1,
                )
            except Exception as e:
                print(e)
                pass
            thread.save()
