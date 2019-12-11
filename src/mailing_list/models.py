from django.db import models
from django.utils import timezone


class EmailRecipient(models.Model):
    email = models.EmailField(unique=True)
    do_not_email = models.BooleanField(default=False)
    is_opted_out = models.BooleanField(default=False)
    is_subscribed = models.BooleanField(default=False)
    bounced_date = models.BooleanField(default=None, null=True)
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
