from django.db import models

from utils.models import DefaultModel


class UsdFundraiseContribution(DefaultModel):
    """
    Tracks individual USD contributions to fundraises.
    Separate from UsdBalance to enable displaying contributors.
    """

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
