from celery.decorators import periodic_task
from celery.task.schedules import crontab

from django.utils import timezone
from datetime import timedelta

from discussion.lib import (
    check_comment_in_threads,
    check_reply_in_threads,
    check_reply_in_comments
)
from discussion.models import Comment, Reply, Thread
from mailing_list.lib import base_email_context
from mailing_list.models import EmailRecipient, NotificationFrequencies
from researchhub.celery import app
from user.tasks import get_latest_actions
from utils.message import send_email_message
from user.models import Action

@app.task
def notify_immediate(action_id):
    actions_notifications([action_id], NotificationFrequencies.IMMEDIATE)

@periodic_task(run_every=crontab(minute='30', hour='1'), priority=7)
def notify_daily():
    interval = timezone.now() - timedelta(days=1)
    action_ids = list(Action.objects.filter(created_date__gte=interval).values_list('id', flat=True))

    actions_notifications(action_ids, NotificationFrequencies.DAILY)

@periodic_task(run_every=crontab(minute='0', hour='*/3'), priority=7)
def notify_three_hours():
    interval = timezone.now() - timedelta(hours=3)
    action_ids = list(Action.objects.filter(created_date__gte=interval).values_list('id', flat=True))

    actions_notifications(action_ids, NotificationFrequencies.THREE_HOUR)

def actions_notifications(action_ids, notif_interval=NotificationFrequencies.IMMEDIATE):
    actions = Action.objects.filter(id__in=action_ids)
    user_to_action = {}
    for action in actions:
        for user in set(action.item.users_to_notify):
            r = user.emailrecipient
            if r.receives_notifications and notif_interval == r.notification_frequency:
                if user_to_action.get(r):
                    user_to_action[r].append(action)
                else:
                    user_to_action[r] = [action]

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
    # TODO: Change subject based on frequency and include action info
    prefix = 'Research Hub | '
    if notification_frequency == NotificationFrequencies.IMMEDIATE:
        return f'{prefix}Updates'
    elif notification_frequency == NotificationFrequencies.DAILY:
        return f'{prefix}Updates'
    elif notification_frequency == NotificationFrequencies.THREE_HOUR:
        return f'{prefix}Updates'
    else:
        return f'{prefix}Updates'

def build_notification_context(actions):
    return {**base_email_context, 'actions': list(actions)}
