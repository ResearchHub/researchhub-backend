from mailing_list.models import EmailRecipient, ThreadSubscription


class TestData:
    valid_email = 'validemail@quantfive.org'
    notification_frequency = EmailRecipient.NOTIFICATION_FREQUENCIES['ALL']


def create_thread_subscription(none=False, comments=True, replies=True):
    return ThreadSubscription.objects.create(
        none=none,
        comments=comments,
        replies=replies
    )


def create_email_recipient(
    user=None,
    thread_subscription=None,
    notification_frequency=TestData.notification_frequency
):
    if not user:
        email = TestData.valid_email
    else:
        email = user.email

    return EmailRecipient.objects.create(
        email=email,
        user=user,
        notification_frequency=notification_frequency,
        thread_subscription=thread_subscription
    )
