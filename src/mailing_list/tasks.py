import logging

from celery.decorators import periodic_task
from celery.task.schedules import crontab

from django.utils import timezone
from django.db.models import Q, Count

from datetime import timedelta

from mailing_list.lib import base_email_context
from mailing_list.models import NotificationFrequencies
from researchhub.celery import app
from utils.message import send_email_message
from user.models import Action, User
from hub.models import Hub
from paper.models import Paper, Vote as PaperVote
from researchhub.settings import TESTING

import time

@app.task
def notify_immediate(action_id):
    # TODO switch signals to save method
    # TODO @val I think this is why I think signals are unreliable
    i = 0
    while not Action.objects.filter(id=action_id).exists() and i < 10:
        time.sleep(.1)
        i += 1
    actions_notifications([action_id], NotificationFrequencies.IMMEDIATE)

@periodic_task(run_every=crontab(minute='30', hour='1'), priority=7)
def notify_daily():
    interval = timezone.now() - timedelta(days=1)
    action_ids = list(
        Action.objects.filter(
            created_date__gte=interval
        ).values_list('id', flat=True)
    )

    actions_notifications(action_ids, NotificationFrequencies.DAILY)

@periodic_task(run_every=crontab(minute='0', hour='*/3'), priority=7)
def notify_three_hours():
    interval = timezone.now() - timedelta(hours=3)
    action_ids = list(
        Action.objects.filter(
            created_date__gte=interval
        ).values_list('id', flat=True)
    )

    actions_notifications(action_ids, NotificationFrequencies.THREE_HOUR)

@periodic_task(run_every=crontab(minute=0, hour=15, day_of_week='friday'), priority=9)
def notify_weekly():
    end_date = timezone.now()
    start_date = timezone.now() - timedelta(days=7)

    upvotes = Count(
        'vote',
        filter=Q(
            vote__vote_type=PaperVote.UPVOTE,
            vote__updated_date__gte=start_date,
            vote__updated_date__lte=end_date
        )
    )

    downvotes = Count(
        'vote',
        filter=Q(
            vote__vote_type=PaperVote.DOWNVOTE,
            vote__created_date__gte=start_date,
            vote__created_date__lte=end_date
        )
    )

    # TODO don't include censored threads?
    thread_counts = Count(
        'threads',
        filter=Q(
            threads__created_date__gte=start_date,
            threads__created_date__lte=end_date,
            #threads__is_removed=False,
        )
    )

    comment_counts = Count(
        'threads__comments',
        filter=Q(
            threads__comments__created_date__gte=start_date,
            threads__comments__created_date__lte=end_date,
            #threads__comments__is_removed=False,
        )
    )

    reply_counts = Count(
        'threads__comments__replies',
        filter=Q(
            threads__comments__replies__created_date__gte=start_date,
            threads__comments__replies__created_date__lte=end_date,
            #threads__comments__replies__is_removed=False,
        )
    )

    users = Hub.objects.filter(subscribers__isnull=False).values_list('subscribers', flat=True)

    # TODO find best by hub and then in mem sort for each user? is more efficient?
    for user in User.objects.filter(id__in=users):
        users_papers = Paper.objects.filter(hubs__in=user.subscribed_hubs.all())
        most_voted_and_uploaded_in_interval = users_papers.filter(uploaded_date__gte=start_date, uploaded_date__lte=end_date).annotate(score=upvotes - downvotes).filter(score__gt=0).order_by('-score')[:3]
        most_discussed_in_interval = users_papers.annotate(discussions=thread_counts + comment_counts + reply_counts).order_by('-discussions')[:3]
        most_voted_in_interval = users_papers.annotate(score=upvotes - downvotes).filter(score__gt=0).order_by('-score')[:2]
        papers = (most_voted_and_uploaded_in_interval and most_discussed_in_interval and most_voted_in_interval)
        if len(papers) == 0:
            continue

        email_context = {
            **base_email_context,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'papers': papers,
            'preview_text': papers[0].tagline
        }

        recipient = [user.email]
        # subject = 'Research Hub | Your Weekly Digest'
        subject = papers[0].title[0:86] + '...'
        email_sent = send_email_message(
            recipient,
            'weekly_digest_email.txt',
            subject,
            email_context,
            'weekly_digest_email.html',
            'ResearchHub Digest <digest@researchhub.com>'
        )

def actions_notifications(
    action_ids,
    notif_interval=NotificationFrequencies.IMMEDIATE
):
    actions = Action.objects.filter(id__in=action_ids)
    user_to_action = {}
    for action in actions:
        if hasattr(action.item, 'users_to_notify'):
            for user in set(action.item.users_to_notify):
                try:
                    r = user.emailrecipient
                    if r.receives_notifications and (
                        notif_interval == r.notification_frequency
                    ):
                        if user_to_action.get(r):
                            user_to_action[r].append(action)
                        else:
                            user_to_action[r] = [action]
                except AttributeError as e:
                    logging.warning(e)
        else:
            logging.info('action: ({action}) is missing users_to_notify field')

    for r in user_to_action:
        subject = build_subject(r.notification_frequency)
        context = build_notification_context(user_to_action[r])
        send_email_message(
            r.email,
            'notification_email.txt',
            subject,
            context,
            html_template='notification_email.html'
        )

def build_subject(notification_frequency):
    prefix = 'Research Hub | '
    if notification_frequency == NotificationFrequencies.IMMEDIATE:
        return f'{prefix}Update'
    elif notification_frequency == NotificationFrequencies.DAILY:
        return f'{prefix}Daily Updates'
    elif notification_frequency == NotificationFrequencies.THREE_HOUR:
        return f'{prefix}Periodic Updates'
    else:
        return f'{prefix}Updates'

def build_notification_context(actions):
    return {**base_email_context, 'actions': [act.email_context() for act in actions]}
