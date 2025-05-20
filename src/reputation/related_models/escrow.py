import time

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from reputation.distributions import (
    create_bounty_distriution,
    create_bounty_refund_distribution,
    create_fundraise_distribution,
    create_stored_paper_pot,
)
from utils.models import DefaultModel


def get_current_bounty_fee():
    from reputation.related_models.bounty_fee import BountyFee

    RH_PCT = 0.07
    DAO_PCT = 0.02

    bounty_fee = BountyFee.objects.last()
    if bounty_fee:
        return bounty_fee.id
    bounty_fee = BountyFee.objects.create(rh_pct=RH_PCT, dao_pct=DAO_PCT)
    return bounty_fee.id


class Escrow(DefaultModel):
    BOUNTY = "BOUNTY"
    AUTHOR_RSC = "AUTHOR_RSC"
    FUNDRAISE = "FUNDRAISE"
    hold_type_choices = (
        (BOUNTY, BOUNTY),
        (AUTHOR_RSC, AUTHOR_RSC),
        (FUNDRAISE, FUNDRAISE),
    )

    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    status_choices = (
        (PAID, PAID),
        (PARTIALLY_PAID, PARTIALLY_PAID),
        (PENDING, PENDING),
        (CANCELLED, CANCELLED),
        (EXPIRED, EXPIRED),
    )

    hold_type = models.CharField(choices=hold_type_choices, max_length=16)
    amount_holding = models.DecimalField(default=0, decimal_places=10, max_digits=19)
    amount_paid = models.DecimalField(default=0, decimal_places=10, max_digits=19)
    recipients = models.ManyToManyField(
        "user.User",
        blank=True,
        related_name="target_escrows",
        through="EscrowRecipients",
    )
    created_by = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="created_escrows"
    )

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey(
        "content_type",
        "object_id",
    )
    status = models.CharField(choices=status_choices, default=PENDING, max_length=16)
    bounty_fee = models.ForeignKey(
        "reputation.BountyFee", on_delete=models.CASCADE, default=get_current_bounty_fee
    )

    class Meta:
        indexes = (models.Index(fields=("content_type", "object_id")),)

    def set_status(self, status, should_save=True):
        self.status = status
        if should_save:
            self.save()

    def set_paid_status(self, should_save=True):
        self.set_status(self.PAID, should_save=should_save)

    def set_partially_paid_status(self, should_save=True):
        self.set_status(self.PARTIALLY_PAID, should_save=should_save)

    def set_cancelled_status(self, should_save=True):
        self.set_status(self.CANCELLED, should_save=should_save)

    def set_expired_status(self, should_save=True):
        self.set_status(self.EXPIRED, should_save=should_save)

    def set_pending_status(self, should_save=True):
        self.set_status(self.PENDING, should_save=should_save)

    def payout(self, recipient, payout_amount):
        from notification.models import Notification
        from reputation.distributor import Distributor

        if not recipient:
            return False

        escrow_amount = self.amount_holding

        status = self.PARTIALLY_PAID
        if payout_amount == self.amount_holding:
            status = self.PAID

        if payout_amount > escrow_amount:
            return False

        if self.hold_type == self.BOUNTY:
            distribution = create_bounty_distriution(payout_amount)
        if self.hold_type == self.FUNDRAISE:
            distribution = create_fundraise_distribution(payout_amount)
        else:
            distribution = create_stored_paper_pot(payout_amount)

        distributor = Distributor(
            distribution, recipient, self, time.time(), giver=self.created_by
        )
        record = distributor.distribute()
        self.recipients.add(recipient, through_defaults={"amount": payout_amount})

        if record.distributed_status == "FAILED":
            return False

        self.amount_holding -= payout_amount
        self.amount_paid += payout_amount
        if status == self.PARTIALLY_PAID:
            self.set_partially_paid_status(should_save=True)
        else:
            self.set_paid_status(should_save=True)

        if self.hold_type == self.BOUNTY:
            unified_document = self.item.unified_document
            notification = Notification.objects.create(
                unified_document=unified_document,
                recipient=recipient,
                action_user=self.created_by,
                item=self,
                notification_type=Notification.BOUNTY_PAYOUT,
            )
            notification.send_notification()
        elif self.hold_type == self.FUNDRAISE:
            unified_document = self.item.unified_document
            notification = Notification.objects.create(
                unified_document=unified_document,
                recipient=recipient,
                action_user=self.created_by,
                item=self,
                notification_type=Notification.FUNDRAISE_PAYOUT,
            )
            notification.send_notification()
        return True

    def refund(self, recipient, amount, status=None):
        from reputation.distributor import Distributor

        if amount == 0:
            return True

        # Validate refund amount doesn't exceed remaining escrow
        if amount > self.amount_holding:
            return False

        distribution = create_bounty_refund_distribution(amount)
        distributor = Distributor(
            distribution,
            recipient,
            self,
            time.time(),
            # Giver is recipient because they originally created the bounty
            giver=recipient,
        )
        record = distributor.distribute()
        if record.distributed_status == "FAILED":
            return False

        # Update escrow amount_holding
        self.amount_holding -= amount
        self.save()

        if status and self.status not in (self.PAID, self.PARTIALLY_PAID):
            self.set_cancelled_status(should_save=True)

        if status == self.EXPIRED:
            self.set_expired_status(should_save=True)

        return True


class EscrowRecipients(DefaultModel):
    escrow = models.ForeignKey(Escrow, on_delete=models.CASCADE)
    amount = models.DecimalField(default=0, decimal_places=10, max_digits=19)
    user = models.ForeignKey("user.User", on_delete=models.CASCADE)
