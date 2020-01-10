from discussion.lib import check_comment_in_threads, check_reply_in_threads
from discussion.models import Comment, Reply, Thread
from mailing_list.lib import base_email_context
from mailing_list.models import EmailRecipient, NotificationFrequencies
from researchhub.celery import app
from user.tasks import get_latest_actions
from utils.message import send_email_message


@app.task
def send_action_notification_emails(email_recipient_ids):
    for email_recipient_id in email_recipient_ids:
        try:
            email_recipient = EmailRecipient.objects.get(pk=email_recipient_id)
            if email_recipient.user is None:
                # TODO: get non-user actions?
                pass
            else:
                actions, actions_by_type, next_cursor = get_subscribed_actions(
                    email_recipient.user,
                    email_recipient.next_cursor,
                    email_recipient.thread_subscription
                )
            send_action_notification_email(
                email_recipient,
                actions,
                actions_by_type,
                next_cursor
            )
        except Exception:
            # TODO: Handle this better
            pass


def get_subscribed_actions(user, action_cursor, thread_subscription):
    """Returns subscribed actions, subscribed actions by type, and the next
        action cursor.
    """
    # TODO: Refactor
    actions, next_cursor = get_latest_actions(action_cursor)

    # TODO: Add more than threads here
    user_threads = Thread.objects.filter(created_by=user)

    subscribed_actions = []
    subscribed_actions_by_type = {}

    for action in actions:
        item = action.item
        content_type = item.content_type

        if isinstance(item, Comment):

            if thread_subscription.comments and not thread_subscription.none:
                if check_comment_in_threads(item, user_threads):
                    subscribed_actions.append(action)
                    try:
                        subscribed_actions_by_type[content_type].append(action)
                    except KeyError:
                        subscribed_actions_by_type[content_type] = [action]

        elif isinstance(item, Reply):

            if thread_subscription.replies and not thread_subscription.none:
                if check_reply_in_threads(item, user_threads):
                    subscribed_actions.append(action)
                    try:
                        subscribed_actions_by_type[content_type].append(action)
                    except KeyError:
                        subscribed_actions_by_type[content_type] = [action]

    return subscribed_actions, subscribed_actions_by_type, next_cursor


def send_action_notification_email(
    email_recipient,
    actions,
    actions_by_type,
    next_cursor
):
    subject = build_subject(email_recipient.notification_frequency, actions[0])
    context = build_notification_context(actions_by_type)

    # TODO: Replace with name of email template
    send_email_message(
        email_recipient,
        'email_template.txt',
        subject,
        context,
        html_message='email_template.html'
    )
    # TODO: check for success first
    email_recipient.next_cursor = next_cursor
    email_recipient.save()


def build_subject(notification_frequency, action):
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


def build_notification_context(actions_by_type):
    return {**base_email_context, **actions_by_type}
