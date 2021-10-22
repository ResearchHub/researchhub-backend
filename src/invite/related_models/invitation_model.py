import pytz

from django.db import models
from django.utils.crypto import get_random_string
from datetime import datetime, timedelta

from user.constants.gatekeeper_constants import ELN
from user.models import User, Gatekeeper
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
        related_name='%(class)s_sent_invites',
        on_delete=models.CASCADE
    )
    key = models.CharField(
        max_length=32,
        unique=True
    )
    recipient = models.ForeignKey(
        User,
        null=True,
        related_name='%(class)s_invitations',
        on_delete=models.CASCADE
    )
    recipient_email = models.CharField(
        max_length=64
    )

    @classmethod
    def create(cls, expiration_time=1440, recipient=None, **kwargs):
        expiration_delta = timedelta(minutes=expiration_time)
        expiration_date = datetime.now(pytz.utc) + expiration_delta
        key = get_random_string(32).lower()
        instance = cls._default_manager.create(
            expiration_date=expiration_date,
            key=key,
            recipient=recipient,
            **kwargs
        )
        return instance

    def accept(self):
        self.accepted = True
        self.save()

        email = self.recipient_email
        if not Gatekeeper.objects.filter(email=email, type=ELN).exists():
            Gatekeeper.objects.create(
                email=self.recipient_email,
                type=ELN
            )

    def is_expired(self):
        return datetime.now(pytz.utc) > self.expiration_date

    def send_invitation(self):
        raise NotImplementedError(
            'You should implement the send_invitation method'
        )
