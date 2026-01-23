from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from utils.models import DefaultModel


class FundingCredit(DefaultModel):
    """
    Transaction-based funding credit tracking.
    Each record represents a credit (positive) or debit (negative).
    The user's total balance is the sum of all their FundingCredit amounts.

    Funding credits are non-liquid rewards earned from staking RSC.
    They can ONLY be spent on funding research proposals (fundraises).
    """

    class CreditType(models.TextChoices):
        STAKING_REWARD = "STAKING_REWARD", "Staking Reward"
        FUNDRAISE_CONTRIBUTION = "FUNDRAISE_CONTRIBUTION", "Fundraise Contribution"

    user = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="funding_credits"
    )
    amount = models.DecimalField(
        max_digits=19,
        decimal_places=10,
        help_text="Amount in RSC-equivalent. Positive = earned, negative = spent",
    )
    credit_type = models.CharField(
        max_length=32,
        choices=CreditType.choices,
    )

    # Generic foreign key to track source of transaction
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True, blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    source = GenericForeignKey("content_type", "object_id")

    class Meta:
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["created_date"]),
            models.Index(fields=["credit_type"]),
        ]

    def __str__(self):
        return f"FundingCredit({self.user_id}, {self.amount}, {self.credit_type})"
