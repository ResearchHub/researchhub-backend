from django.db import models

from utils.models import DefaultModel


class UsdFundraiseContribution(DefaultModel):
    """
    Tracks individual USD contributions to fundraises.
    Separate from UsdBalance to enable displaying contributors.
    amount_rsc is the RSC equivalent at contribution date (for leaderboard).
    """

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
    amount_rsc = models.DecimalField(
        max_digits=19,
        decimal_places=8,
        null=True,
        blank=True,
        help_text="RSC equivalent at contribution date",
    )

    class Meta:
        indexes = [
            models.Index(fields=["fundraise"]),
            models.Index(fields=["user"]),
        ]
