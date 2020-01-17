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
def send_action_notification_emails(email_recipient_ids):
    for email_recipient_id in email_recipient_ids:
        email_recipient = EmailRecipient.objects.get(pk=email_recipient_id)
        if email_recipient.user is None:
            # TODO: get non-user actions?
            pass
        else:
            subscribed_actions = SubscribedActions(email_recipient)
            (
                actions,
                actions_by_type,
                next_cursor
            ) = subscribed_actions.get_subscribed_actions()

        if len(actions) > 0:
            send_action_notification_email(
                email_recipient,
                actions,
                actions_by_type,
                next_cursor
            )


@app.task
def send_email_simple(email_list, action_id):
    """
    Sends an email to a specified email list
    """
    action = Action.objects.get(id=action_id)
    subject = build_subject(NotificationFrequencies.IMMEDIATE)
    context = build_notification_context([action])
    result = send_email_message(
        email_list,
        'notification_email.txt',
        subject,
        context,
        html_template='notification_email.html'
    )


class SubscribedActions:
    def __init__(self, email_recipient):
        self.email_recipient = email_recipient
        self.actions = set()
        self.actions_by_type = {}
        self.formatted_actions = []

    def get_subscribed_actions(self):
        """Returns subscribed actions, subscribed actions by type, and the next
        action cursor.

        Args:
            email_recipient (obj) -- EmailRecipient instance with a user. If
            the user field is None the function
            `get_non_user_subscribed_actions` should be used instead of this.
        """

        user = self.email_recipient.user
        action_cursor = self.email_recipient.next_cursor

        thread_subscription = self.email_recipient.thread_subscription
        comment_subscription = self.email_recipient.comment_subscription

        actions, next_cursor = get_latest_actions(action_cursor)

        # TODO: Add more than threads here
        user_threads = Thread.objects.filter(created_by=user)
        user_comments = Comment.objects.filter(created_by=user)

        for action in actions:
            item = action.item

            if action.item.created_by != user:

                if isinstance(item, Comment):

                    if (
                        thread_subscription.comments
                        and not thread_subscription.none
                    ):
                        if check_comment_in_threads(item, user_threads):
                            self.add(action)

                elif isinstance(item, Reply):

                    if (
                        thread_subscription.replies
                        and not thread_subscription.none
                    ):
                        if check_reply_in_threads(item, user_threads):
                            self.add(action)

                    if (
                        comment_subscription.replies
                        and not comment_subscription.none
                    ):
                        if check_reply_in_comments(item, user_comments):
                            self.add(action)

        return (
            self.formatted_actions,
            self.actions_by_type,
            next_cursor
        )

    def add(self, action):
        content_type = str(action.content_type)

        if action not in self.actions:
            self.actions.add(action)
            self.add_formatted_action(action)
            try:
                self.actions_by_type[content_type].add(action)
            except KeyError:
                self.actions_by_type[content_type] = set([action])

    def add_formatted_action(self, action):
        formatted_action = {
            'item': action.item,
            'label': self.get_action_label(action.item),
            'created_date': self.get_action_created_date(action),
            'initials': action.item.created_by.author_profile.first_name[0] + action.item.created_by.author_profile.last_name[0], 
        }
        self.formatted_actions.append(formatted_action)

    def get_action_label(self, action_item):
        if isinstance(action_item, Comment):
            return 'commented on your thread'
        elif isinstance(action_item, Reply):
            return 'replied to your comment'

    def get_action_created_date(self, action):
        # TODO: Format this
        return action.created_date


def send_action_notification_email(
    email_recipient,
    actions,
    actions_by_type,
    next_cursor
):
    subject = build_subject(email_recipient.notification_frequency)
    context = build_notification_context(actions)

    result = send_email_message(
        email_recipient.email,
        'notification_email.txt',
        subject,
        context,
        html_template='notification_email.html'
    )
    # TODO: check for success first
    print(result)
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


def build_notification_context(actions):
    return {**base_email_context, 'actions': list(actions)}
