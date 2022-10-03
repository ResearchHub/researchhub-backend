from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Sum

from utils.models import DefaultModel


def get_default_expiration_date():
    now = datetime.now(pytz.UTC)
    date = now + timedelta(days=31)
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
    amount = models.DecimalField(default=0, decimal_places=10, max_digits=19)
    created_by = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="bounties"
    )
    escrow = models.OneToOneField(
        "reputation.escrow", on_delete=models.CASCADE, related_name="bounty"
    )
    status = models.CharField(choices=status_choices, default=OPEN, max_length=16)
    unified_document = models.ForeignKey(
        "researchhub_document.ResearchhubUnifiedDocument",
        on_delete=models.CASCADE,
        related_name="related_bounties",
    )
    actions = GenericRelation("user.Action")

    class Meta:
        indexes = (
            models.Index(
                fields=(
                    "item_content_type",
                    "item_object_id",
                )
            ),
        )

    def __str__(self):
        return f"Bounty: {self.id}"

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

    def expiry_close(self):
        from reputation.models import Escrow

        document_type = self.unified_document.document_type

        if document_type == "QUESTION" or document_type == "POST":
            threads = self.unified_document.posts.first().threads
        elif document_type == "PAPER":
            threads = self.unified_document.paper.threads
        elif document_type == "HYPOTHESIS":
            threads = self.unified_document.hypothesis.first().threads
        else:
            return None

        thread_count = threads.count()
        thread_score_total = threads.aggregate(total_score=Sum("votes__vote_type"))
        thread_score_dict = {}

        self.escrow.status = Escrow.EXPIRY_CLOSED
        self.escrow.save()

        for thread in threads.all():
            escrow_percent = thread.score / thread_score_total["total_score"]
            cur_amount = self.escrow.amount * Decimal(escrow_percent)
            cur_escrow = self.escrow

            escrow = Escrow.objects.create(
                hold_type=Escrow.BOUNTY,
                amount=cur_amount,
                bounty_for_expiry=self,
                recipient=thread.created_by,
                created_by=cur_escrow.created_by,
                content_type=cur_escrow.content_type,
                object_id=cur_escrow.object_id,
                item=cur_escrow.item,
                status=Escrow.EXPIRY_PAID,
                bounty_fee=cur_escrow.bounty_fee,
            )
            escrow.payout(payout_amount=cur_amount)
            escrow.status = Escrow.EXPIRY_PAID
            escrow.save()

        self.set_expired_status()

    def approve(self, payout_amount=None):
        if not payout_amount:
            payout_amount = self.amount

        if payout_amount > self.amount:
            return False

        escrow_paid = self.escrow.payout(payout_amount=payout_amount)
        self.set_closed_status(should_save=False)
        return escrow_paid

    def refund(self):
        return self.escrow.refund()

    def cancel(self):
        self.set_cancelled_status()
        return self.refund()


class BountySolution(DefaultModel):
    bounty = models.ForeignKey(
        Bounty, on_delete=models.CASCADE, related_name="solutions"
    )
    created_by = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="solutions"
    )
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="bounty_solution"
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey(
        "content_type",
        "object_id",
    )
