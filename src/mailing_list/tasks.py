import logging

from celery.decorators import periodic_task
from celery.task.schedules import crontab
from django.utils import timezone
from django.db.models import Q, Count
from django.http.request import HttpRequest
from rest_framework.request import Request
from datetime import timedelta

from mailing_list.lib import base_email_context
from mailing_list.models import NotificationFrequencies, EmailTaskLog
from researchhub.celery import app
from utils.message import send_email_message
from user.models import Action, User
from hub.models import Hub
from paper.models import Paper, Vote as PaperVote
from paper.views import PaperViewSet


@app.task
def notify_immediate(action_id):
    actions_notifications([action_id], NotificationFrequencies.IMMEDIATE)


@periodic_task(run_every=crontab(minute='30', hour='1'), priority=7)
def notify_daily():
    # TODO: Temporarily turning off notifications - Revamp
    return
    send_hub_digest(NotificationFrequencies.DAILY)


@periodic_task(run_every=crontab(minute='0', hour='*/3'), priority=7)
def notify_three_hours():
    send_hub_digest(NotificationFrequencies.THREE_HOUR)


# Noon PST
@periodic_task(
    run_every=crontab(minute=0, hour=20, day_of_week='friday'),
    priority=9
)
def notify_weekly():
    send_hub_digest(NotificationFrequencies.WEEKLY)


def send_hub_digest(frequency):
    etl = EmailTaskLog.objects.create(
        emails='',
        notification_frequency=frequency
    )
    end_date = timezone.now()
    start_date = calculate_hub_digest_start_date(end_date, frequency)

    users = Hub.objects.filter(
        subscribers__isnull=False,
        is_removed=False,
    ).values_list('subscribers', flat=True)

    # TODO find best by hub and then in mem sort for each user? more efficient?
    emails = []
    for user in User.objects.filter(id__in=users, is_suspended=False):
        if not check_can_receive_digest(user, frequency):
            continue

        paper_view = PaperViewSet()
        http_req = HttpRequest()
        http_meta = {
            'QUERY_STRING': '',
            'HTTP_HOST': 'localhost',
            'HTTP_X_FORWARDED_PROTO': 'http',
        }
        http_req.META = http_meta
        req = Request(http_req)
        req.GET = {
            'use_cache': False,
            'subscribed_hubs': True,
            'page': 1,
            'start_date__gte': start_date.timestamp(),
            'end_date__lte': end_date.timestamp()
        }
        req.user = user
        paper_view.request = req
        paper_view.format_kwarg = lambda x: x
        user_papers = paper_view.get_hub_papers(req)
        papers = user_papers.data['results']['data']

        if len(papers) == 0:
            print(f'No papers for user: {user.email}')
            continue

        email_context = {
            **base_email_context,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'papers': papers,
            'preview_text': papers[0]['tagline']
        }

        recipient = [user.email]
        # subject = 'Research Hub | Your Weekly Digest'
        subject = papers[0]['title'][0:86] + '...'
        send_email_message(
            recipient,
            'weekly_digest_email.txt',
            subject,
            email_context,
            'weekly_digest_email.html',
            'ResearchHub Digest <digest@researchhub.com>'
        )
        emails += recipient

    etl.emails = ','.join(emails)
    etl.save()


def calculate_hub_digest_start_date(end_date, frequency):
    if frequency == NotificationFrequencies.DAILY:
        return end_date - timedelta(days=1)
    elif frequency == NotificationFrequencies.THREE_HOUR:
        return end_date - timedelta(hours=3)
    else:  # weekly
        return end_date - timedelta(days=7)


def actions_notifications(
    action_ids,
    notif_interval=NotificationFrequencies.IMMEDIATE
):
    # NOTE: This only supports immediate updates for now.
    actions = Action.objects.filter(id__in=action_ids)
    user_to_action = {}
    for action in actions:
        if hasattr(action.item, 'users_to_notify'):
            for user in set(action.item.users_to_notify):
                try:
                    r = user.emailrecipient
                    if r.receives_notifications:
                        if user_to_action.get(r):
                            user_to_action[r].append(action)
                        else:
                            user_to_action[r] = [action]
                except AttributeError as e:
                    logging.warning(e)
        else:
            logging.info('action: ({action}) is missing users_to_notify field')

    for r in user_to_action:
        subject = build_subject(notif_interval)
        context = build_notification_context(user_to_action[r])
        send_email_message(
            r.email,
            'notification_email.txt',
            subject,
            context,
            html_template='notification_email.html'
        )


def build_subject(notification_frequency):
    prefix = 'ResearchHub | '
    if notification_frequency == NotificationFrequencies.IMMEDIATE:
        return f'{prefix}Update'
    elif notification_frequency == NotificationFrequencies.DAILY:
        return f'{prefix}Daily Updates'
    elif notification_frequency == NotificationFrequencies.THREE_HOUR:
        return f'{prefix}Periodic Updates'
    else:
        return f'{prefix}Updates'


def build_notification_context(actions):
    return {
        **base_email_context,
        'actions': [act.email_context() for act in actions]
    }


def check_can_receive_digest(user, frequency):
    try:
        email_recipient = user.emailrecipient
        return (
            email_recipient.receives_notifications
            and not email_recipient.digest_subscription.none
            and (email_recipient.digest_subscription.notification_frequency == frequency)  # noqa: E501
        )
    except Exception:
        return False
