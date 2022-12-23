import time

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from reputation.distributions import (
    create_bounty_distriution,
    create_bounty_refund_distribution,
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
    hold_type_choices = (
        (BOUNTY, BOUNTY),
        (AUTHOR_RSC, AUTHOR_RSC),
    )

    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"
    EXPIRY_CLOSED = "EXPIRY_CLOSED"
    EXPIRY_PAID = "EXPIRY_PAID"
    status_choices = (
        (PAID, PAID),
        (PARTIALLY_PAID, PARTIALLY_PAID),
        (PENDING, PENDING),
        (CANCELLED, CANCELLED),
        (EXPIRY_CLOSED, EXPIRY_CLOSED),
        (EXPIRY_PAID, EXPIRY_PAID),
    )

    hold_type = models.CharField(choices=hold_type_choices, max_length=16)
    amount = models.DecimalField(default=0, decimal_places=10, max_digits=19)
    amount_paid = models.DecimalField(default=0, decimal_places=10, max_digits=19)
    connected_bounty = models.ForeignKey(
        "reputation.bounty", on_delete=models.CASCADE, related_name="escrows", null=True
    )  # This is only here to payout multiple bounties
    recipient = models.ForeignKey(
        "user.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="target_escrows",
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

    def set_pending_status(self, should_save=True):
        self.set_status(self.PENDING, should_save=should_save)

    def _get_net_payout(self, payout_amount, escrow_amount):
        net_payout = payout_amount
        refund_amount = escrow_amount - net_payout
        return net_payout, refund_amount

    def payout(self, payout_amount):
        from reputation.distributor import Distributor

        recipient = self.recipient
        escrow_amount = self.amount

        if not recipient:
            return False

        status = self.PARTIALLY_PAID
        if payout_amount == self.amount:
            status = self.PAID

        if payout_amount > escrow_amount:
            return False

        net_payout, refund_amount = self._get_net_payout(payout_amount, escrow_amount)
        distribution = create_bounty_distriution(net_payout)
        distributor = Distributor(
            distribution, recipient, self, time.time(), giver=self.created_by
        )
        record = distributor.distribute()
        if record.distributed_status == "FAILED":
            return False

        self.amount_paid = net_payout
        if status == self.PARTIALLY_PAID:
            self.refund(refund_amount)
        else:
            self.set_paid_status(should_save=False)

        from notification.models import Notification
        from researchhub_document.models import ResearchhubUnifiedDocument

        action_user = self.created_by
        action_user_name = action_user.first_name
        document = (
            ResearchhubUnifiedDocument.objects.get(id=self.object_id)
            if self.content_type
            == ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
            else None
        )
        doc_title = None
        comments_url = None
        body = None

        def _truncate_title(title):
            if len(title) > 75:
                title = f"{title[:75]}..."
            return title

        if document:
            doc_title = _truncate_title(title=document.get_document().title)
            base_url = document.frontend_view_link()
            comments_url = f"{base_url}#comments"

            body = [
                {
                    "type": "link",
                    "value": f"{action_user_name}",
                    "extra": '["bold", "link"]',
                    "link": action_user.frontend_view_link(),
                },
                {
                    "type": "text",
                    "value": "awarded you {} RSC for your ".format(payout_amount),
                },
                {
                    "type": "link",
                    "value": "thread ",
                    "link": comments_url,
                    "extra": '["link"]',
                },
                {"type": "text", "value": "in "},
                {
                    "type": "link",
                    "value": doc_title,
                    "link": base_url,
                    "extra": '["link"]',
                },
            ]

        import pdb

        pdb.set_trace()
        notification = Notification.objects.create(
            item=self,
            unified_document_id=self.object_id
            if self.content_type
            == ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
            else None,
            notification_type="BOUNTY_PAYOUT",
            recipient=self.recipient,
            action_user=self.created_by,
            navigation_url=comments_url,
            body=body,
        )

        notification.send_notification()

        return True

    def refund(self, amount=None):
        from reputation.distributor import Distributor

        status = self.PARTIALLY_PAID
        if amount is None:
            amount = self.amount
            status = self.CANCELLED

        distribution = create_bounty_refund_distribution(amount)
        distributor = Distributor(
            distribution,
            self.created_by,
            self,
            time.time(),
        )
        record = distributor.distribute()
        if record.distributed_status == "FAILED":
            return False

        if status == self.PARTIALLY_PAID:
            self.set_partially_paid_status(should_save=False)
        else:
            self.set_cancelled_status()
            self.save()
        return True
