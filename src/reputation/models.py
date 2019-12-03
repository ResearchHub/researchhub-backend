from django.contrib.postgres.fields import JSONField
from django.db import models
from django.utils import timezone

import ethereum.lib
import reputation.distributions as distributions
from user.models import User
from utils.models import SoftDeletableModel


class PaidStatusModelMixin(models.Model):
    FAILED = 'failed'
    PAID = 'paid'
    PENDING = 'pending'
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

    def set_pending(self):
        self.paid_status = self.PENDING
        self.save()

    def set_paid(self):
        self.paid_status = self.PAID
        self.paid_date = timezone.now()
        self.save()


class Distribution(SoftDeletableModel, PaidStatusModelMixin):
    DISTRIBUTION_TYPE_CHOICES = [
        (
            distributions.CreatePaper.name,
            distributions.CreatePaper.name
        ),
        (
            distributions.CommentEndorsed.name,
            distributions.CommentEndorsed.name
        ),
        (
            distributions.CommentFlagged.name,
            distributions.CommentFlagged.name
        ),
        (
            distributions.CommentUpvoted.name,
            distributions.CommentUpvoted.name
        ),
        (
            distributions.CommentDownvoted.name,
            distributions.CommentDownvoted.name
        ),
        (
            distributions.ReplyEndorsed.name,
            distributions.ReplyEndorsed.name
        ),
        (
            distributions.ReplyFlagged.name,
            distributions.ReplyFlagged.name
        ),
        (
            distributions.ReplyUpvoted.name,
            distributions.ReplyUpvoted.name
        ),
        (
            distributions.ReplyDownvoted.name,
            distributions.ReplyDownvoted.name
        ),
        (
            distributions.ThreadEndorsed.name,
            distributions.ThreadEndorsed.name
        ),
        (
            distributions.ThreadFlagged.name,
            distributions.ThreadFlagged.name
        ),
        (
            distributions.ThreadUpvoted.name,
            distributions.ThreadUpvoted.name
        ),
        (
            distributions.ThreadDownvoted.name,
            distributions.ThreadDownvoted.name
        ),
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
    distribution_type = models.CharField(
        max_length=255,
        choices=DISTRIBUTION_TYPE_CHOICES
    )
    proof = JSONField()
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
    amount_integer_part = models.BigIntegerField()
    amount_decimal_part = models.BigIntegerField()
    from_address = models.CharField(max_length=255)
    to_address = models.CharField(max_length=255)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    transaction_hash = models.CharField(
        default='',
        blank=True,
        max_length=255
    )
