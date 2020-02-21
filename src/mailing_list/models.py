from django.db import models
from django.utils import timezone

from mailing_list.lib import NotificationFrequencies


class SubscriptionField(models.OneToOneField):
    def __init__(self, *args, **kwargs):
        kwargs['on_delete'] = models.SET_NULL
        kwargs['null'] = True
        return super().__init__(*args, **kwargs)


class EmailRecipient(models.Model):
    """Subscriptions define what category of content a user is notified about
    and how often they are notified, but not what they are subscribed to.
    """
    email = models.EmailField(unique=True)
    do_not_email = models.BooleanField(default=False)
    is_opted_out = models.BooleanField(default=False)
    is_subscribed = models.BooleanField(default=True)
    next_cursor = models.IntegerField(default=0)
    user = models.OneToOneField(
        'user.User',
        on_delete=models.SET_NULL,
        default=None,
        null=True
    )
    digest_subscription = SubscriptionField(
        'mailing_list.DigestSubscription',
        related_name='email_recipient'
    )
    paper_subscription = SubscriptionField(
        'mailing_list.PaperSubscription',
        related_name='email_recipient'
    )
    comment_subscription = SubscriptionField(
        'mailing_list.CommentSubscription',
        related_name='email_recipient'
    )
    thread_subscription = SubscriptionField(
        'mailing_list.ThreadSubscription',
        related_name='email_recipient'
    )
    reply_subscription = SubscriptionField(
        'mailing_list.ReplySubscription',
        related_name='email_recipient'
    )
    bounced_date = models.DateTimeField(default=None, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.email}'

    def save(self, *args, **kwargs):
        # TODO: Replace this with a mgmt command. Does not need to be in
        # application logic.

        return super(EmailRecipient, self).save(*args, **kwargs)

    def bounced(self):
        self.bounced_date = timezone.now()
        self.do_not_email = True
        self.save()

    def set_opted_out(self, opt_out):
        self.is_opted_out = opt_out
        self.save()

    def set_subscribed(self, subscribed):
        self.is_subscribed = subscribed
        self.save()

    # TODO check this logic
    @property
    def receives_notifications(self):
        return (
            not self.do_not_email
            and not self.is_opted_out
            and self.is_subscribed
        )


class BaseSubscription(models.Model):
    NOTIFICATION_FREQUENCY_CHOICES = (
        ('IMMEDIATE', NotificationFrequencies.IMMEDIATE),
        ('DAILY', NotificationFrequencies.DAILY),
        ('WEEKLY', NotificationFrequencies.WEEKLY),
    )
    notification_frequency = models.IntegerField(
        default=NotificationFrequencies.IMMEDIATE,
        choices=NOTIFICATION_FREQUENCY_CHOICES
    )

    class Meta:
        abstract = True

    def __str__(self):
        # TODO: Strip hidden functions
        return str(self.__dict__.items())


class DigestSubscription(BaseSubscription):
    notification_frequency = models.IntegerField(
        default=NotificationFrequencies.DAILY,
        choices=BaseSubscription.NOTIFICATION_FREQUENCY_CHOICES
    )
    none = models.BooleanField(default=False)


class PaperSubscription(BaseSubscription):
    none = models.BooleanField(default=False)
    threads = models.BooleanField(default=True)


class ThreadSubscription(BaseSubscription):
    none = models.BooleanField(default=False)
    comments = models.BooleanField(default=True)


class CommentSubscription(BaseSubscription):
    none = models.BooleanField(default=False)
    replies = models.BooleanField(default=True)


class ReplySubscription(BaseSubscription):
    none = models.BooleanField(default=False)
    replies = models.BooleanField(default=True)
