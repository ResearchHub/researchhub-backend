'''
Send events to google analytics
'''
from django.utils import timezone
from django.core.management.base import BaseCommand

from bullet_point.models import BulletPoint
from discussion.models import Vote as DiscussionVote, Comment, Reply, Thread
from google_analytics.signals import (
    send_bullet_point_event,
    send_discussion_event,
    send_paper_event,
    send_user_event,
    send_vote_event
)
from paper.models import Paper, Vote as PaperVote
from user.models import User


class Command(BaseCommand):
    help = (
        f'Sends google analytics events for items created before the'
        f' specified date'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'created_or_updated',
            type=str,
            help='one of "created" or "updated"'
        )
        parser.add_argument(
            'after',
            type=str,
            help='after datetime'
        )
        parser.add_argument(
            'before',
            type=str,
            help='before datetime e.g. YYYY-MM-DD HH:MM:SS'
        )

    def handle(self, *args, **options):
        date_filter = options['created_or_updated']
        assert ('created' in date_filter) or ('updated' in date_filter)

        created = 'created' in date_filter

        after_date_filter = f'{date_filter}_date__gt'
        before_date_filter = f'{date_filter}_date__lt'
        after_dt = timezone.datetime.fromisoformat(options['after'])
        before_dt = timezone.datetime.fromisoformat(options['before'])

        filters = {
            after_date_filter: after_dt,
            before_date_filter: before_dt
        }

        paper_filters = {
            'uploaded_by__isnull': False,
            **filters
        }
        if created:
            papers = Paper.objects.filter(
                uploaded_by__isnull=False,
                uploaded_date__gt=after_dt,
                uploaded_date__lt=before_dt
            )
        else:
            papers = Paper.objects.filter(**paper_filters)
        for paper in papers:
            response = send_paper_event(Paper, paper, created, [])
            print(response)

        bullet_points = BulletPoint.objects.filter(**filters)
        for bp in bullet_points:
            response = send_bullet_point_event(BulletPoint, bp, created, [])
            print(response)
        discussion_votes = DiscussionVote.objects.filter(**filters)
        for dv in discussion_votes:
            response = send_vote_event(DiscussionVote, dv, created, [])
            print(response)
        paper_votes = PaperVote.objects.filter(**filters)
        for pv in paper_votes:
            response = send_vote_event(PaperVote, pv, created, [])
            print(response)
        threads = Thread.objects.filter(**filters)
        for thread in threads:
            response = send_discussion_event(Thread, thread, created, [])
            print(response)
        comments = Comment.objects.filter(**filters)
        for comment in comments:
            response = send_discussion_event(Comment, comment, created, [])
            print(response)
        replies = Reply.objects.filter(**filters)
        for reply in replies:
            response = send_discussion_event(Reply, reply, created, [])
            print(response)
        users = User.objects.filter(**filters)
        for user in users:
            response = send_user_event(User, user, created, [])
            print(response)

        self.stdout.write(self.style.SUCCESS(
            'Done sending google analytics events'
        ))
