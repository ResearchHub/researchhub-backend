from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import JSONField
from django.utils import timezone

import reputation.distributions as distributions
from hub.models import Hub
from reputation.related_models.paid_status_mixin import PaidStatusModelMixin
from utils.models import SoftDeletableModel


class Distribution(SoftDeletableModel, PaidStatusModelMixin):
    DISTRIBUTION_TYPE_CHOICES = distributions.DISTRIBUTION_TYPE_CHOICES

    FAILED = "FAILED"
    DISTRIBUTED = "DISTRIBUTED"
    PENDING = "PENDING"
    DISTRIBUTED_STATUS_CHOICES = [
        (FAILED, FAILED),
        (DISTRIBUTED, DISTRIBUTED),
        (PENDING, PENDING),
    ]

    recipient = models.ForeignKey(
        "user.User",
        related_name="reputation_records",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    giver = models.ForeignKey(
        "user.User",
        related_name="reputation_handed_out",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    hubs = models.ManyToManyField(
        Hub,
        related_name="reputation_records",
    )
    amount = models.BigIntegerField(default=0)  # RSC Amount
    reputation_amount = models.IntegerField(default=0)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    distribution_type = models.CharField(
        max_length=255, choices=DISTRIBUTION_TYPE_CHOICES
    )
    proof_item_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True
    )
    proof_item_object_id = models.PositiveIntegerField(null=True)
    proof_item = GenericForeignKey(
        "proof_item_content_type",
        "proof_item_object_id",
    )
    proof = JSONField(null=True)
    distributed_date = models.DateTimeField(default=None, null=True)
    distributed_status = models.CharField(
        max_length=255, choices=DISTRIBUTED_STATUS_CHOICES, default=None, null=True
    )
    withdrawal = models.ForeignKey(
        "reputation.Withdrawal", on_delete=models.CASCADE, default=None, null=True
    )

    def __str__(self):
        return (
            f"Distribution: {self.distribution_type},"
            f" Recipient: {self.recipient},"
            f" Amount: {self.amount}"
        )

    def set_distributed_failed(self):
        self.distributed_status = self.FAILED
        self.save()

    def set_distributed_pending(self):
        self.distributed_status = self.PENDING
        self.save()

    def set_distributed(self):
        self.distributed_status = self.DISTRIBUTED
        self.distributed_date = timezone.now()
        self.save()

    def set_withdrawal(self, withdrawal_instance):
        self.withdrawal = withdrawal_instance
        self.save()
