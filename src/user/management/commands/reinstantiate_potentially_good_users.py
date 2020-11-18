from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from datetime import timedelta, datetime
from django.utils import timezone

from user.models import User
from discussion.models import Thread, Comment, Reply
import uuid

class Command(BaseCommand):

    def handle(self, *args, **options):
        # three_days_ago = timezone.now().date() - timedelta(days=3)
        static_start_date = datetime(
            year=2020,
            month=10,
            day=29,
            hour=0,
            minute=0,
        )
        objects = User.objects.filter(created_date__lte=static_start_date)
        count = objects.count()
        for i, user in enumerate(objects):
            print('{} / {}'.format(i, count))
            user.probable_spammer = False
            user.is_suspended = False
            user.paper_votes.update(is_removed=False)
            user.papers.update(is_removed=False)
            Thread.objects.filter(created_by=user).update(is_removed=False)
            Comment.objects.filter(created_by=user).update(is_removed=False)
            Reply.objects.filter(created_by=user).update(is_removed=False)
            user.save()
