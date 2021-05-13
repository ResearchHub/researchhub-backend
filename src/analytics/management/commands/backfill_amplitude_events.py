import time
import requests
import json

from pytz import timezone

from django.db.models import Count
from django.db.models.functions import TruncDay
from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from user.models import User, Action
from purchase.models import Purchase
from paper.models import Paper
from researchhub.settings import AMPLITUDE_API_KEY, APP_ENV


API_URL = 'https://api.amplitude.com/2/httpapi'


class Command(BaseCommand):
    def get_user_props(self, user, user_email):
        # Makes one less db call if user email is passed in
        invited_by = user.invited_by
        if invited_by:
            invited_by_id = invited_by.id
        else:
            invited_by_id = None

        user_properties = {
            'email': user_email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'reputation': user.reputation,
            'is_suspended': user.is_suspended,
            'probable_spammer': user.probable_spammer,
            'invited_by_id': invited_by_id
        }
        return user_properties

    def forward_amp_event(self, events):
        event_data = {
            'api_key': AMPLITUDE_API_KEY,
            'events': events
        }
        data = json.dumps(event_data)
        headers = {
          'Content-Type': 'application/json',
          'Accept': '*/*'
        }
        request = requests.post(
            API_URL,
            data=data,
            headers=headers
        )
        res = request.json()
        if request.status_code != 200:
            res = request.json()
            print(res)
        print(res)

    def handle_comments(self, comments):
        print('Comments')
        count = comments.count()
        events = []
        for i, comment in enumerate(comments.iterator()):
            if (i % 1000 == 0 and i != 0) or (count - 1) == i:
                self.forward_amp_event(events)
                events = []
            else:
                print(f'{i}/{count}')
                comment = comment.item
                if comment:
                    user = comment.created_by
                    user_email = user.email
                    user_properties = self.get_user_props(user, user_email)
                    user_id = f'{user_email}_{user.id}'
                    if len(user_id) < 5:
                        user_id += '_____'
                    hit = {
                        'user_id': user_id,
                        'event_type': 'create_comment',
                        'time': int(comment.created_date.timestamp()),
                        'user_properties': user_properties,
                        'insert_id': f'comment_{comment.id}',
                        'is_removed': comment.is_removed,
                    }
                    events.append(hit)
        self.forward_amp_event(events)

    def handle_replies(self, replies):
        print('Replies')
        count = replies.count()
        events = []
        for i, reply in enumerate(replies.iterator()):
            if (i % 1000 == 0 and i != 0) or (count - 1) == i:
                self.forward_amp_event(events)
                events = []
            else:
                print(f'{i}/{count}')
                reply = reply.item
                if reply:
                    user = reply.created_by
                    user_email = user.email
                    user_properties = self.get_user_props(user, user_email)
                    user_id = f'{user_email}_{user.id}'
                    if len(user_id) < 5:
                        user_id += '_____'
                    hit = {
                        'user_id': user_id,
                        'event_type': 'create_reply',
                        'time': int(reply.created_date.timestamp()),
                        'user_properties': user_properties,
                        'insert_id': f'reply_{reply.id}',
                        'is_removed': reply.is_removed,
                    }
                    events.append(hit)
        self.forward_amp_event(events)

    def handle_threads(self, threads):
        print('Threads')
        count = threads.count()
        events = []
        for i, thread in enumerate(threads.iterator()):
            if (i % 1000 == 0 and i != 0) or (count - 1) == i:
                self.forward_amp_event(events)
                events = []
            else:
                print(f'{i}/{count}')
                thread = thread.item
                if thread:
                    user = thread.created_by
                    user_email = user.email
                    user_properties = self.get_user_props(user, user_email)
                    user_id = f'{user_email}_{user.id}'
                    if len(user_id) < 5:
                        user_id += '_____'
                    hit = {
                        'user_id': user_id,
                        'event_type': 'create_thread',
                        'time': int(thread.created_date.timestamp()),
                        'user_properties': user_properties,
                        'insert_id': f'thread_{thread.id}',
                        'is_removed': thread.is_removed,
                    }
                    events.append(hit)
        self.forward_amp_event(events)

    def handle_dis_votes(self, votes):
        print('Discussion Votes')
        count = votes.count()
        events = []
        for i, vote in enumerate(votes.iterator()):
            if (i % 1000 == 0 and i != 0) or (count - 1) == i:
                self.forward_amp_event(events)
                events = []
            else:
                print(f'{i}/{count}')
                vote = vote.item
                if vote:
                    user = vote.created_by
                    user_email = user.email
                    user_properties = self.get_user_props(user, user_email)
                    user_id = f'{user_email}_{user.id}'
                    if len(user_id) < 5:
                        user_id += '_____'
                    hit = {
                        'user_id': user_id,
                        'event_type': 'create_discussion_vote',
                        'time': int(vote.created_date.timestamp()),
                        'user_properties': user_properties,
                        'insert_id': f'dis_vote_{vote.id}'
                    }
                    events.append(hit)
        self.forward_amp_event(events)

    def handle_papers(self, papers):
        print('Papers')
        count = papers.count()
        events = []
        for i, paper in enumerate(papers.iterator()):
            if (i % 1000 == 0 and i != 0) or (count - 1) == i:
                self.forward_amp_event(events)
                events = []
            else:
                print(f'{i}/{count}')
                paper = paper.item
                if paper:
                    user = paper.uploaded_by
                    user_email = user.email
                    user_properties = self.get_user_props(user, user_email)
                    user_id = f'{user_email}_{user.id}'
                    if len(user_id) < 5:
                        user_id += '_____'
                    hit = {
                        'user_id': user_id,
                        'event_type': 'create_paper',
                        'time': int(paper.uploaded_date.timestamp()),
                        'user_properties': user_properties,
                        'insert_id': f'paper_{paper.id}',
                        'is_removed': paper.is_removed,
                    }
                    events.append(hit)
        self.forward_amp_event(events)

    def handle_paper_votes(self, votes):
        print('Paper Votes')
        count = votes.count()
        events = []
        for i, vote in enumerate(votes.iterator()):
            if (i % 1000 == 0 and i != 0) or (count - 1) == i:
                self.forward_amp_event(events)
                events = []
            else:
                print(f'{i}/{count}')
                vote = vote.item
                if vote:
                    user = vote.created_by
                    user_email = user.email
                    user_properties = self.get_user_props(user, user_email)
                    user_id = f'{user_email}_{user.id}'
                    if len(user_id) < 5:
                        user_id += '_____'
                    hit = {
                        'user_id': user_id,
                        'event_type': 'create_paper_vote',
                        'time': int(vote.created_date.timestamp()),
                        'user_properties': user_properties,
                        'insert_id': f'paper_vote_{vote.id}'
                    }
                    events.append(hit)
        self.forward_amp_event(events)

    def handle_summaries(self, summaries):
        print('Summaries')
        count = summaries.count()
        events = []
        for i, summary in enumerate(summaries.iterator()):
            if (i % 1000 == 0 and i != 0) or (count - 1) == i:
                self.forward_amp_event(events)
                events = []
            else:
                print(f'{i}/{count}')
                summary = summary.item
                if summary:
                    user = summary.proposed_by
                    user_email = user.email
                    user_properties = self.get_user_props(user, user_email)
                    user_id = f'{user_email}_{user.id}'
                    if len(user_id) < 5:
                        user_id += '_____'
                    hit = {
                        'user_id': user_id,
                        'event_type': 'create_summary',
                        'time': int(summary.created_date.timestamp()),
                        'user_properties': user_properties,
                        'insert_id': f'summary_{summary.id}'
                    }
                    events.append(hit)
        self.forward_amp_event(events)

    def handle_bulletpoints(self, bulletpoints):
        print('Bulletpoints')
        count = bulletpoints.count()
        events = []
        for i, bulletpoint in enumerate(bulletpoints.iterator()):
            if (i % 1000 == 0 and i != 0) or (count - 1) == i:
                self.forward_amp_event(events)
                events = []
            else:
                print(f'{i}/{count}')
                bulletpoint = bulletpoint.item
                if bulletpoint:
                    user = bulletpoint.created_by
                    user_email = user.email
                    user_properties = self.get_user_props(user, user_email)
                    user_id = f'{user_email}_{user.id}'
                    if len(user_id) < 5:
                        user_id += '_____'
                    hit = {
                        'user_id': user_id,
                        'event_type': 'create_bulletpoints',
                        'time': int(bulletpoint.created_date.timestamp()),
                        'user_properties': user_properties,
                        'insert_id': f'bulletpoint_{bulletpoint.id}'
                    }
                    events.append(hit)
        self.forward_amp_event(events)

    def handle_user_signup(self, users):
        print('Users')
        count = users.count()
        events = []
        for i, user in enumerate(users.iterator()):
            if (i % 1000 == 0 and i != 0) or (count - 1) == i:
                self.forward_amp_event(events)
                events = []
            else:
                print(f'{i}/{count}')
                user_email = user.email
                user_properties = self.get_user_props(user, user_email)
                user_id = f'{user_email}_{user.id}'
                if len(user_id) < 5:
                    user_id += '_____'
                hit = {
                    'user_id': user_id,
                    'event_type': 'user_signup',
                    'time': int(user.date_joined.timestamp()),
                    'user_properties': user_properties,
                    'insert_id': f'user_{user.id}'
                }
                events.append(hit)
        self.forward_amp_event(events)

    def handle_purchases(self, purchases):
        print('Purchases')
        count = purchases.count()
        events = []
        for i, purchase in enumerate(purchases.iterator()):
            if (i % 1000 == 0 and i != 0) or (count - 1) == i:
                self.forward_amp_event(events)
                events = []
            else:
                print(f'{i}/{count}')
                user = purchase.user
                user_email = user.email
                user_properties = self.get_user_props(user, user_email)
                user_id = f'{user_email}_{user.id}'
                if len(user_id) < 5:
                    user_id += '_____'
                hit = {
                    'user_id': user_id,
                    'event_type': 'create_purchase',
                    'time': int(purchase.created_date.timestamp()),
                    'user_properties': user_properties,
                    'insert_id': f'purchase_{purchase.id}',
                    'event_properties': {
                        'interaction': purchase.purchase_method,
                        'amount': purchase.amount,
                        'object_id': purchase.object_id,
                        'content_type': purchase.content_type.model
                    }
                }
                events.append(hit)
        self.forward_amp_event(events)

    def handle_autopull_uploads(self):
        print('Autopull')
        papers = Paper.objects.all().filter(
            uploaded_by__isnull=True
        ).annotate(
            date=TruncDay('uploaded_date', tzinfo=timezone('US/Pacific'))
        ).order_by(
            '-date'
        ).values(
            'date'
        ).annotate(
            count=Count('date')
        )
        count = papers.count()
        events = []
        for i, paper in enumerate(papers.iterator()):
            if (i % 1000 == 0 and i != 0) or (count - 1) == i:
                self.forward_amp_event(events)
                events = []
            else:
                print(f'{i}/{count}')
                date = paper['date']
                paper_count = paper['count']
                timestamp = time.mktime(date.timetuple())
                hit = {
                    'device_id': f'rh_{APP_ENV}',
                    'event_type': 'daily_autopull_count',
                    'time': int(timestamp),
                    'insert_id': f"daily_autopull_{date.strftime('%Y-%m-%d')}",
                    'event_properties': {
                        'amount': paper_count,
                    }
                }
                events.append(hit)
        self.forward_amp_event(events)

    def handle(self, *args, **options):
        comment_ct = ContentType.objects.get(model='comment')
        reply_ct = ContentType.objects.get(model='reply')
        thread_ct = ContentType.objects.get(model='thread')
        dis_vote_ct = ContentType.objects.get(
            app_label='discussion',
            model='vote'
        )
        paper_ct = ContentType.objects.get(model='paper')
        paper_vote_ct = ContentType.objects.get(
            app_label='paper',
            model='vote'
        )
        summary_ct = ContentType.objects.get(model='summary')
        bullet_point_ct = ContentType.objects.get(model='bulletpoint')

        comment = Action.objects.exclude(
            user=None
        ).filter(
            content_type=comment_ct
        )
        reply = Action.objects.exclude(
            user=None
        ).filter(
            content_type=reply_ct
        )
        thread = Action.objects.exclude(
            user=None
        ).filter(
            content_type=thread_ct
        )
        dis_vote = Action.objects.filter(content_type=dis_vote_ct)
        paper = Action.objects.exclude(
            user=None
        ).filter(
            content_type=paper_ct
        )
        paper_vote = Action.objects.filter(content_type=paper_vote_ct)
        summary = Action.objects.exclude(
            user=None
        ).filter(
            content_type=summary_ct
        )
        bulletpoint = Action.objects.exclude(
            user=None
        ).filter(
            content_type=bullet_point_ct
        )
        user = User.objects
        purchase = Purchase.objects

        # self.handle_comments(comment)
        # self.handle_replies(reply)
        # self.handle_threads(thread)
        # self.handle_dis_votes(dis_vote)
        # self.handle_papers(paper)
        # self.handle_paper_votes(paper_vote)
        # self.handle_summaries(summary)
        # self.handle_bulletpoints(bulletpoint)
        # self.handle_user_signup(user)
        # self.handle_purchases(purchase)
        self.handle_autopull_uploads()
