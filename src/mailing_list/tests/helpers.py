from mailing_list.lib import NotificationFrequencies
from mailing_list.models import (
    CommentSubscription,
    EmailRecipient,
    ThreadSubscription
)


class TestData:
    valid_email = 'validemail@quantfive.org'
    notification_frequency = NotificationFrequencies.IMMEDIATE


def create_thread_subscription(none=False, comments=True, replies=True):
    return ThreadSubscription.objects.create(
        none=none,
        comments=comments,
        replies=replies
    )


def create_comment_subscription(none=False, replies=True):
    return CommentSubscription.objects.create(
        none=none,
        replies=replies
    )


def create_email_recipient(
    user=None,
    thread_subscription=None,
):
    if not user:
        email = TestData.valid_email
    else:
        email = user.email

    return EmailRecipient.objects.create(
        email=email,
        user=user,
        thread_subscription=thread_subscription
    )
