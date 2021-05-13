from django.db import models
from django.utils import timezone

from mailing_list.lib import NotificationFrequencies

class EmailTaskLog(models.Model):
    emails = models.TextField()
    notification_frequency = models.IntegerField(
        default=NotificationFrequencies.IMMEDIATE,
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

class SubscriptionField(models.OneToOneField):
    def __init__(self, *args, **kwargs):
        kwargs['on_delete'] = models.CASCADE
        kwargs['null'] = True
        return super().__init__(*args, **kwargs)


class EmailRecipient(models.Model):
    """Subscriptions define what category of content a user is notified about
    and how often they are notified, but not what they are subscribed to.
    """
    email = models.EmailField(unique=True)
    do_not_email = models.BooleanField(default=False)
    is_opted_out = models.BooleanField(default=False)
    next_cursor = models.IntegerField(default=0)
    user = models.OneToOneField(
        'user.User',
        on_delete=models.CASCADE,
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
        if self.digest_subscription is None:
            self.digest_subscription = DigestSubscription.objects.create()
        if self.paper_subscription is None:
            self.paper_subscription = PaperSubscription.objects.create()
        if self.thread_subscription is None:
            self.thread_subscription = ThreadSubscription.objects.create()
        if self.comment_subscription is None:
            self.comment_subscription = CommentSubscription.objects.create()
        if self.reply_subscription is None:
            self.reply_subscription = ReplySubscription.objects.create()
        return super(EmailRecipient, self).save(*args, **kwargs)

    def bounced(self):
        self.bounced_date = timezone.now()
        self.do_not_email = True
        self.save()

    def set_opted_out(self, opt_out):
        self.is_opted_out = opt_out
        self.save()

    @property
    def receives_notifications(self):
        return not self.do_not_email and not self.is_opted_out


class BaseSubscription(models.Model):
    NOTIFICATION_FREQUENCY_CHOICES = (
        ('IMMEDIATE', NotificationFrequencies.IMMEDIATE),
        ('THREE_HOUR', NotificationFrequencies.THREE_HOUR),
        ('DAILY', NotificationFrequencies.DAILY),
        ('WEEKLY', NotificationFrequencies.WEEKLY),
    )
    notification_frequency = models.IntegerField(
        default=NotificationFrequencies.IMMEDIATE,
        choices=NOTIFICATION_FREQUENCY_CHOICES
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def __str__(self):
        # TODO: Strip hidden functions
        return str(self.__dict__.items())

    def unsubscribe(self):
        self.none = True
        self.save()


class DigestSubscription(BaseSubscription):
    notification_frequency = models.IntegerField(
        default=NotificationFrequencies.WEEKLY,
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
