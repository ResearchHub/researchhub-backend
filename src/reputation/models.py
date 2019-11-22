from django.contrib.postgres.fields import JSONField
from django.db import models

import reputation.distributions as distributions
from user.models import User
from utils.models import SoftDeletableModel


class Distribution(SoftDeletableModel):
    DISTRIBUTION_TYPE_CHOICES = [
        (distributions.CreatePaper.name, distributions.CreatePaper.name),
        (
            distributions.CommentEndorsed.name,
            distributions.CommentEndorsed.name
        ),
        (distributions.CommentFlagged.name, distributions.CommentFlagged.name),
        (distributions.CommentUpvoted.name, distributions.CommentUpvoted.name),
        (
            distributions.CommentDownvoted.name,
            distributions.CommentDownvoted.name
        ),
        (distributions.ReplyEndorsed.name, distributions.ReplyEndorsed.name),
        (distributions.ReplyFlagged.name, distributions.ReplyFlagged.name),
        (distributions.ReplyUpvoted.name, distributions.ReplyUpvoted.name),
        (distributions.ReplyDownvoted.name, distributions.ReplyDownvoted.name),
        (distributions.ThreadEndorsed.name, distributions.ThreadEndorsed.name),
        (distributions.ThreadFlagged.name, distributions.ThreadFlagged.name),
        (distributions.ThreadUpvoted.name, distributions.ThreadUpvoted.name),
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

    def __str__(self):
        return (
            f'Distribution: {self.distribution_type},'
            f' Recipient: {self.recipient},'
            f' Amount: {self.amount}'
        )


class Withdrawal(SoftDeletableModel):
    # TOKEN_ADDRESS_CHOICES = ethereum.lib.TOKEN_ADDRESS_CHOICES

    user = models.ForeignKey(
        User,
        related_name='withdrawals',
        on_delete=models.SET_NULL,
        null=True
    )
    # token_address = models.CharField(max_length=255, choices=TOKEN_ADDRESS_CHOICES)
    amount_integer_part = models.BigIntegerField()
    amount_decimal_part = models.BigIntegerField()
    from_address = models.CharField(max_length=255)
    to_address = models.CharField(max_length=255)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    paid_date = models.DateTimeField(default=None, null=True)
    is_paid = models.BooleanField(default=False)
    transaction_hash = models.CharField(
        default='',
        blank=True,
        max_length=255
    )
