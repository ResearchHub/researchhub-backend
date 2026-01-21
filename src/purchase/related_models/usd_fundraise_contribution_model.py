from django.db import models

from utils.models import DefaultModel


class UsdFundraiseContribution(DefaultModel):
    """
    Tracks individual USD contributions to fundraises.
    Separate from UsdBalance to enable displaying contributors.
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

    class Meta:
        indexes = [
            models.Index(fields=["fundraise"]),
            models.Index(fields=["user"]),
        ]
