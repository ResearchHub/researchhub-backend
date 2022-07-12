from datetime import datetime, timedelta

import pytz
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from utils.models import DefaultModel


def get_default_expiration_date():
    now = datetime.now(pytz.UTC)
    date = now + timedelta(days=30)
    return date


class Bounty(DefaultModel):
    OPEN = "OPEN"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"
    status_choices = (
        (OPEN, OPEN),
        (CLOSED, CLOSED),
        (CANCELLED, CANCELLED),
        (EXPIRED, EXPIRED),
    )

    expiration_date = models.DateTimeField(
        null=True, default=get_default_expiration_date
    )
    item_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="item_bounty"
    )
    item_object_id = models.PositiveIntegerField()
    item = GenericForeignKey(
        "item_content_type",
        "item_object_id",
    )
    solution_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="solution_bounty",
        null=True,
        blank=True,
    )
    solution_object_id = models.PositiveIntegerField(null=True, blank=True)
    solution = GenericForeignKey(
        "solution_content_type",
        "solution_object_id",
    )
    amount = models.DecimalField(default=0, decimal_places=10, max_digits=19)
    created_by = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="bounties"
    )
    escrow = models.OneToOneField(
        "reputation.escrow", on_delete=models.CASCADE, related_name="bounty"
    )
    status = models.CharField(choices=status_choices, default=OPEN, max_length=16)

    def set_status(self, status, should_save=True):
        self.status = status
        if should_save:
            self.save()

    def set_cancelled_status(self, should_save=True):
        self.set_status(self.CANCELLED, should_save=should_save)

    def set_expired_status(self, should_save=True):
        self.set_status(self.EXPIRED, should_save=should_save)

    def set_closed_status(self, should_save=True):
        self.set_status(self.CLOSED, should_save=should_save)

    def approve(self, payout_amount=None):
        if not payout_amount:
            payout_amount = self.amount

        if payout_amount > self.amount:
            return False

        escrow_paid = self.escrow.payout(payout_amount=payout_amount)
        self.set_closed_status(should_save=False)
        return escrow_paid

    def cancel(self):
        self.set_cancelled_status()
        return self.escrow.refund()
