from django.db import models
from django.utils import timezone

from utils.parsers import dict_to_tuple

NOTIFICATION_FREQUENCIES = {  # In minutes
    'IMMEDIATE': 0,
    'DAILY': 1440,
    '3HOUR': 180,
}


class SubscriptionField(models.OneToOneField):
    def __init__(self, *args, **kwargs):
        kwargs['on_delete'] = models.SET_NULL
        kwargs['null'] = True
        return super().__init__(*args, **kwargs)


class EmailRecipient(models.Model):
    NOTIFICATION_FREQUENCIES = NOTIFICATION_FREQUENCIES
    NOTIFICATION_FREQUENCY_CHOICES = dict_to_tuple(NOTIFICATION_FREQUENCIES)
    email = models.EmailField(unique=True)
    do_not_email = models.BooleanField(default=False)
    is_opted_out = models.BooleanField(default=False)
    is_subscribed = models.BooleanField(default=False)
    notification_frequency = models.IntegerField(
        choices=NOTIFICATION_FREQUENCY_CHOICES
    )
    user = models.OneToOneField(
        'user.User',
        on_delete=models.SET_NULL,
        default=None,
        null=True
    )
    thread_subscription = SubscriptionField(
        'mailing_list.ThreadSubscription',
        related_name='email_recipient'
    )
    bounced_date = models.DateTimeField(default=None, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.email}'

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


class ThreadSubscription(models.Model):
    none = models.BooleanField(default=False)
    comments = models.BooleanField(default=True)
    replies = models.BooleanField(default=True)

    def __str__(self):
        # TODO: Strip hidden functions
        return str(self.__dict__.items())
