import time

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction

from reputation.distributions import (
    create_bounty_distriution,
    create_bounty_refund_distribution,
    create_fundraise_distribution,
)
from utils.models import DefaultModel


def get_current_bounty_fee():
    from reputation.related_models.bounty_fee import BountyFee

    rh_pct = 0.07
    dao_pct = 0.02

    bounty_fee = BountyFee.objects.last()
    if bounty_fee:
        return bounty_fee.id
    bounty_fee = BountyFee.objects.create(rh_pct=rh_pct, dao_pct=dao_pct)
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

        with transaction.atomic():
            escrow = Escrow.objects.select_for_update().get(pk=self.pk)

            if escrow.status in (escrow.PAID, escrow.CANCELLED, escrow.EXPIRED):
                return False

            if payout_amount > escrow.amount_holding:
                return False

            status = escrow.PARTIALLY_PAID
            if payout_amount == escrow.amount_holding:
                status = escrow.PAID

            if escrow.hold_type == escrow.BOUNTY:
                distribution = create_bounty_distriution(payout_amount)
            elif escrow.hold_type == escrow.FUNDRAISE:
                distribution = create_fundraise_distribution(payout_amount)
            else:
                raise ValueError(
                    f"Cannot payout escrow {escrow.pk}: unsupported "
                    f"hold_type={escrow.hold_type!r}"
                )

            distributor = Distributor(
                distribution, recipient, escrow, time.time(), giver=escrow.created_by
            )
            record = distributor.distribute()
            escrow.recipients.add(recipient, through_defaults={"amount": payout_amount})

            if record.distributed_status == "FAILED":
                return False

            escrow.amount_holding -= payout_amount
            escrow.amount_paid += payout_amount
            if status == escrow.PARTIALLY_PAID:
                escrow.set_partially_paid_status(should_save=True)
            else:
                escrow.set_paid_status(should_save=True)

            if escrow.hold_type == escrow.BOUNTY:
                unified_document = escrow.item.unified_document
                notification = Notification.objects.create(
                    unified_document=unified_document,
                    recipient=recipient,
                    action_user=escrow.created_by,
                    item=escrow,
                    notification_type=Notification.BOUNTY_PAYOUT,
                    extra={"amount": str(payout_amount)},
                )
                notification.send_notification()
            elif escrow.hold_type == escrow.FUNDRAISE:
                unified_document = escrow.item.unified_document
                notification = Notification.objects.create(
                    unified_document=unified_document,
                    recipient=recipient,
                    action_user=escrow.created_by,
                    item=escrow,
                    notification_type=Notification.FUNDRAISE_PAYOUT,
                )
                notification.send_notification()

            self.amount_holding = escrow.amount_holding
            self.amount_paid = escrow.amount_paid
            self.status = escrow.status

        return True

    def refund(self, recipient, amount, status=None, is_locked=False):
        from reputation.distributor import Distributor

        if amount == 0:
            return True

        with transaction.atomic():
            escrow = Escrow.objects.select_for_update().get(pk=self.pk)

            if amount > escrow.amount_holding:
                return False

            distribution = create_bounty_refund_distribution(amount)
            distributor = Distributor(
                distribution,
                recipient,
                escrow,
                time.time(),
                # Giver is recipient because they originally created the bounty
                giver=recipient,
                is_locked=is_locked,
            )
            record = distributor.distribute()
            if record.distributed_status == "FAILED":
                return False

            escrow.amount_holding -= amount
            escrow.save(update_fields=["amount_holding", "updated_date"])

            if status and escrow.status not in (escrow.PAID, escrow.PARTIALLY_PAID):
                escrow.set_cancelled_status(should_save=True)

            if status == escrow.EXPIRED:
                escrow.set_expired_status(should_save=True)

            self.amount_holding = escrow.amount_holding
            self.status = escrow.status

        return True


class EscrowRecipients(DefaultModel):
    escrow = models.ForeignKey(Escrow, on_delete=models.CASCADE)
    amount = models.DecimalField(default=0, decimal_places=10, max_digits=19)
    user = models.ForeignKey("user.User", on_delete=models.CASCADE)
