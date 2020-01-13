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


@app.task
def send_action_notification_emails(email_recipient_ids):
    for email_recipient_id in email_recipient_ids:
        email_recipient = EmailRecipient.objects.get(pk=email_recipient_id)
        if email_recipient.user is None:
            # TODO: get non-user actions?
            pass
        else:
            actions, actions_by_type, next_cursor = get_subscribed_actions(
                email_recipient
            )

        if len(actions) > 0:
            send_action_notification_email(
                email_recipient,
                actions,
                actions_by_type,
                next_cursor
            )


class SubscribedActions:
    def __init__(self):
        self.actions = []
        self.actions_by_type = {}

    def add(self, action):
        content_type = str(action.content_type)
        self.actions.append(action)
        try:
            self.subscribed_actions_by_type[content_type].append(action)
        except KeyError:
            self.subscribed_actions_by_type[content_type] = [action]


# TODO: Refactor and make this a class method
def get_subscribed_actions(email_recipient):
    """Returns subscribed actions, subscribed actions by type, and the next
    action cursor.

    Args:
        email_recipient (obj) -- EmailRecipient instance with a user. If the
        user field is None the function `get_non_user_subscribed_actions`
        should be used instead of this.

    """

    user = email_recipient.user
    action_cursor = email_recipient.next_cursor

    thread_subscription = email_recipient.thread_subscription
    comment_subscription = email_recipient.comment_subscription

    actions, next_cursor = get_latest_actions(action_cursor)

    # TODO: Add more than threads here
    user_threads = Thread.objects.filter(created_by=user)
    user_comments = Comment.objects.filter(created_by=user)

    subscribed_actions = SubscribedActions()

    for action in actions:
        item = action.item

        if isinstance(item, Comment):

            if thread_subscription.comments and not thread_subscription.none:
                if check_comment_in_threads(item, user_threads):
                    subscribed_actions.add(action)

        elif isinstance(item, Reply):

            if thread_subscription.replies and not thread_subscription.none:
                if check_reply_in_threads(item, user_threads):
                    subscribed_actions.add(action)

            if comment_subscription.replies and not comment_subscription.none:
                if check_reply_in_comments(item, user_comments):
                    subscribed_actions.add(action)

    return (
        subscribed_actions.actions,
        subscribed_actions.actions_by_type,
        next_cursor
    )


def send_action_notification_email(
    email_recipient,
    actions,
    actions_by_type,
    next_cursor
):
    subject = build_subject(email_recipient.notification_frequency)
    context = build_notification_context(actions_by_type)

    # TODO: Replace with name of email template
    result = send_email_message(
        email_recipient.email,
        'notification_email.txt',
        subject,
        context,
        html_message='notification_email.html'
    )
    print('email result', result)
    # TODO: check for success first
    email_recipient.next_cursor = next_cursor
    email_recipient.save()


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


def build_notification_context(actions_by_type):
    return {**base_email_context, **actions_by_type}
