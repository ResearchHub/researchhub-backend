from django.db import models
from django.utils import timezone


class EmailAddress(models.Model):
    email = models.EmailField(unique=True)
    can_receive_email = models.BooleanField(default=True)
    is_opted_out = models.BooleanField(default=False)
    bounced_date = models.BooleanField(default=None, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.email}'

    def bounced(self):
        self.bounced_date = timezone.now()
        self.can_receive_email = False
        self.save()

    def set_opt_out(self, opt_out):
        self.is_opted_out = opt_out
        self.can_receive_email = not opt_out
        self.save()
