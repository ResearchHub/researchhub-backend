from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from django.db.models.functions import Length

from user.models import User
from paper.models import Vote
import uuid

from utils.siftscience import decisions_api, events_api

class Command(BaseCommand):

    def handle(self, *args, **options):
        votes = Vote.objects.filter(created_by__probable_spammer=True, is_removed=False)
        count = votes.count()
        for i, vote in enumerate(votes):
            print('{} / {}'.format(i, count))
            vote.is_removed = True
            content_id = f'{type(vote).__name__}_{vote.id}'
            decisions_api.apply_bad_content_decision(vote.created_by, content_id)
            events_api.track_flag_content(
                vote.created_by,
                content_id,
                1,
            )
            vote.save()
 