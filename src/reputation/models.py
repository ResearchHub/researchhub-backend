from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import JSONField
from django.db import models
from django.utils import timezone

import ethereum.lib
import reputation.distributions as distributions
from user.models import User
from utils.models import SoftDeletableModel


class PaidStatusModelMixin(models.Model):
    FAILED = 'FAILED'
    PAID = 'PAID'
    PENDING = 'PENDING'
    PAID_STATUS_CHOICES = [
        (FAILED, FAILED),
        (PAID, PAID),
        (PENDING, PENDING),
    ]

    class Meta:
        abstract = True

    paid_date = models.DateTimeField(default=None, null=True)
    paid_status = models.CharField(
        max_length=255,
        choices=PAID_STATUS_CHOICES,
        default=None,
        null=True
    )

    def set_paid_failed(self):
        self.paid_status = self.FAILED
        self.save()

    def set_paid_pending(self):
        self.paid_status = self.PENDING
        self.save()

    def set_paid(self):
        self.paid_status = self.PAID
        self.paid_date = timezone.now()
        self.save()


class Distribution(SoftDeletableModel, PaidStatusModelMixin):
    DISTRIBUTION_TYPE_CHOICES = distributions.DISTRIBUTION_TYPE_CHOICES

    FAILED = 'FAILED'
    DISTRIBUTED = 'DISTRIBUTED'
    PENDING = 'PENDING'
    DISTRIBUTED_STATUS_CHOICES = [
        (FAILED, FAILED),
        (DISTRIBUTED, DISTRIBUTED),
        (PENDING, PENDING),
    ]

    recipient = models.ForeignKey(
        User,
        related_name='reputation_records',
        on_delete=models.SET_NULL,
        blank=True,
        null=True
    )
    amount = models.IntegerField(default=0)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    distribution_type = models.CharField(
        max_length=255,
        choices=DISTRIBUTION_TYPE_CHOICES
    )
    proof_item_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    proof_item_object_id = models.PositiveIntegerField()
    proof_item = GenericForeignKey(
        'proof_item_content_type',
        'proof_item_object_id'
    )
    proof = JSONField()
    distributed_date = models.DateTimeField(default=None, null=True)
    distributed_status = models.CharField(
        max_length=255,
        choices=DISTRIBUTED_STATUS_CHOICES,
        default=None,
        null=True
    )
    withdrawal = models.ForeignKey(
        'reputation.Withdrawal',
        on_delete=models.CASCADE,
        default=None,
        null=True
    )

    def __str__(self):
        return (
            f'Distribution: {self.distribution_type},'
            f' Recipient: {self.recipient},'
            f' Amount: {self.amount}'
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


class Withdrawal(SoftDeletableModel, PaidStatusModelMixin):
    TOKEN_ADDRESS_CHOICES = ethereum.lib.TOKEN_ADDRESS_CHOICES

    user = models.ForeignKey(
        User,
        related_name='withdrawals',
        on_delete=models.SET_NULL,
        null=True
    )
    token_address = models.CharField(
        max_length=255,
        choices=TOKEN_ADDRESS_CHOICES
    )
    amount = models.CharField(max_length=255, default='0.0')
    from_address = models.CharField(max_length=255)
    to_address = models.CharField(max_length=255)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    transaction_hash = models.CharField(
        default='',
        blank=True,
        max_length=255
    )
    paid_status = models.CharField(
        max_length=255,
        choices=PaidStatusModelMixin.PAID_STATUS_CHOICES,
        default=PaidStatusModelMixin.PENDING,
    )

    class Meta:
        ordering = ['-updated_date']

