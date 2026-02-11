from django.db import models
from django.db.models import Sum
from django.db.models.functions import Coalesce

from utils.models import DefaultModel


class UsdFundraiseContributionQuerySet(models.QuerySet):
    """QuerySet for UsdFundraiseContribution with chainable filters."""

    def for_user(self, user_id: int):
        """Filter contributions by user."""
        return self.filter(user_id=user_id)

    def exclude_user(self, user_id: int):
        """Exclude contributions by user."""
        return self.exclude(user_id=user_id)

    def not_refunded(self):
        """Filter for non-refunded contributions."""
        return self.filter(is_refunded=False)

    def for_fundraises(self, fundraise_ids):
        """Filter by fundraise IDs."""
        return self.filter(fundraise_id__in=fundraise_ids)

    def sum(self) -> int:
        """Return sum of amount_cents."""
        return self.aggregate(total=Coalesce(Sum("amount_cents"), 0))["total"]

    def sum_usd(self) -> float:
        """Return sum of amounts in USD (converts cents to dollars)."""
        return self.sum() / 100


class UsdFundraiseContribution(DefaultModel):
    """
    Tracks individual USD contributions to fundraises.
    """

    objects = UsdFundraiseContributionQuerySet.as_manager()

    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "SUBMITTED"
        CANCELLED = "CANCELLED", "CANCELLED"

    user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="usd_fundraise_contributions",
    )
    fundraise = models.ForeignKey(
        "purchase.Fundraise", on_delete=models.CASCADE, related_name="usd_contributions"
    )
    amount_cents = models.IntegerField(help_text="Contribution amount in cents")
    fee_cents = models.IntegerField(default=0, help_text="9% fee in cents")
    is_refunded = models.BooleanField(default=False)
    status = models.CharField(
        choices=Status.choices,
        default=Status.SUBMITTED,
        max_length=32,
        help_text="Processual status of the contribution",
    )
    origin_fund_id = models.CharField(
        max_length=255,
        help_text="Origin fund (DAF) ID in Endaoment",
    )
    destination_org_id = models.CharField(
        max_length=255,
        help_text="Intended destination organization ID in Endaoment",
    )
    endaoment_transfer_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Endaoment grant transfer ID (external ID)",
    )

    class Meta:
        indexes = [
            models.Index(fields=["fundraise"]),
            models.Index(fields=["user"]),
        ]

