from django.db import models
from django.utils import timezone

from utils.parsers import dict_to_tuple

NOTIFICATION_FREQUENCIES = {
    'ALL': 'All',
    'DAILY': 'Daily',
    '3HOUR': '3-hour'
}


class EmailRecipient(models.Model):
    NOTIFICATION_FREQUENCIES = NOTIFICATION_FREQUENCIES
    NOTIFICATION_FREQUENCY_CHOICES = dict_to_tuple(NOTIFICATION_FREQUENCIES)
    email = models.EmailField(unique=True)
    do_not_email = models.BooleanField(default=False)
    is_opted_out = models.BooleanField(default=False)
    is_subscribed = models.BooleanField(default=False)
    # notification_frequency = models.CharField(
    #     choices=NOTIFICATION_FREQUENCY_CHOICES
    # )
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
