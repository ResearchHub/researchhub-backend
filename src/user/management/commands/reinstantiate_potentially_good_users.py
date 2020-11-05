from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from datetime import timedelta
from django.utils import timezone

from user.models import User
from discussion.models import Thread, Comment, Reply
import uuid

class Command(BaseCommand):

    def handle(self, *args, **options):
        three_days_ago = timezone.now().date() - timedelta(days=3)
        objects = User.objects.filter(created_date__gte=three_days_ago, is_suspended=True)
        count = objects.count()
        for i, user in enumerate(objects):
            print('{} / {}'.format(i, count))
            user.probable_spam = False
            user.is_suspended = False
            user.votes.update(is_removed=False)
            user.papers.update(is_removed=False)
            Thread.objects.filter(created_by=user).update(is_removed=True)
            Comment.objects.filter(created_by=user).update(is_removed=True)
            Reply.objects.filter(created_by=user).update(is_removed=True)
