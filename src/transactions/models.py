from django.db import models

from user.models import User


class Withdrawl(models.Model):
    user = models.ForeignKey(
        User,
        default=None,
        null=True,
        blank=True,
        related_name='Withdrawl',
        on_delete='SET NULL'
    )
    amount = models.FloatField(default=0)
    transition_id = models.CharField(default=None, null=True, max_length=36)
    from_address = models.CharField(default=None, null=True, max_length=36)
    to_address = models.CharField(default=None, null=True, max_length=36)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
