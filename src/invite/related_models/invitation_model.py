from django.db import models
from django.utils.crypto import get_random_string
from datetime import datetime, timedelta

from user.models import User
from utils.models import DefaultModel


class Invitation(DefaultModel):
    class Meta:
        abstract = True

    accepted = models.BooleanField(
        default=False
    )
    expiration_date = models.DateTimeField()
    inviter = models.ForeignKey(
        User,
        related_name='sent_invites',
        on_delete=models.CASCADE
    )
    key = models.CharField(
        max_length=32,
        unique=True
    )
    recipient = models.ForeignKey(
        User,
        null=True,
        related_name='invitations',
        on_delete=models.CASCADE
    )

    @classmethod
    def create(cls, expiration_time=1440, recipient=None, **kwargs):
        expiration_delta = timedelta(minutes=expiration_time)
        expiration_date = datetime.now() + expiration_delta
        key = get_random_string(32).lower()
        instance = cls._default_manager.create(
            expiration_date=expiration_date,
            key=key,
            recipient=recipient,
            **kwargs
        )
        return instance

    def is_expired(self):
        return datetime.now() > self.expiration_date()

    def send_invitation(self):
        raise NotImplementedError(
            'You should implement the send_invitation method'
        )
