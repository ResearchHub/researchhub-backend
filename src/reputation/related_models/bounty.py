from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.db.models import Sum

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
        null=True,
        default=get_default_expiration_date,  # Can be null for author claim bounties
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
    escrow = models.ForeignKey(
        "reputation.escrow", on_delete=models.CASCADE, related_name="bounties"
    )
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, related_name="children", null=True
    )
    status = models.CharField(choices=status_choices, default=OPEN, max_length=16)
    unified_document = models.ForeignKey(
        "researchhub_document.ResearchhubUnifiedDocument",
        on_delete=models.CASCADE,
        related_name="related_bounties",
    )
    actions = GenericRelation("user.Action")
    contribution = GenericRelation(
        "reputation.Contribution",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="bounty",
    )

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

    def is_open(self):
        return self.status == Bounty.OPEN

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

    def get_bounty_proportions(self):
        children = self.children
        has_children = children.exists()
        values = [(self.created_by.id, self.amount)]
        total_sum = self.amount
        if has_children:
            values.extend(children.values_list("created_by", "amount"))
            children_amount = children.aggregate(children_sum=Sum("amount")).get(
                "children_sum", 0
            )
            total_sum += children_amount

        proportions = {value[0]: value[1] / total_sum for value in values}
        return proportions

    def approve(self, recipient=None, payout_amount=None):
        if not recipient:
            return False

        escrow_paid = self.escrow.payout(
            recipient=recipient, payout_amount=payout_amount
        )
        return escrow_paid

    def close(self, status):
        from user.models import User

        proportions = self.get_bounty_proportions()
        escrow_remaining_amout = self.escrow.amount_holding
        for user_id, percentage in proportions.items():
            refund_amount = escrow_remaining_amout * percentage
            user = User.objects.get(id=user_id)
            refunded = self.escrow.refund(user, refund_amount)
            if not refunded:
                return False

        self.children.update(status=status)
        status_func = getattr(self, f"set_{status.lower()}_status")
        status_func()
        return True


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
    contribution = GenericRelation(
        "reputation.Contribution",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="bounty_solution",
    )
