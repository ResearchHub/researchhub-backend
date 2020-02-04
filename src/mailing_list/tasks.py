import logging

from celery.decorators import periodic_task
from celery.task.schedules import crontab

from django.utils import timezone
from datetime import timedelta

from mailing_list.lib import base_email_context
from mailing_list.models import NotificationFrequencies
from researchhub.celery import app
from utils.message import send_email_message
from user.models import Action

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
    return {**base_email_context, 'actions': list(actions)}
