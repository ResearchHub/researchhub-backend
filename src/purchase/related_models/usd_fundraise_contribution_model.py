from django.db import models

from utils.models import DefaultModel


class UsdFundraiseContribution(DefaultModel):
    """
    Tracks individual USD contributions to fundraises.
    Separate from UsdBalance to enable displaying contributors.
    """

    class Source(models.TextChoices):
        BALANCE = "BALANCE", "BALANCE"
        ENDAOMENT = "ENDAOMENT", "ENDAOMENT"

    class Status(models.TextChoices):
        COMPLETED = "COMPLETED", "COMPLETED"
        RESERVED = "RESERVED", "RESERVED"
        SUBMITTED = "SUBMITTED", "SUBMITTED"
        FAILED = "FAILED", "FAILED"
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
    source = models.CharField(
        max_length=16,
        choices=Source.choices,
        default=Source.BALANCE,
        db_comment="Origin of funds",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.COMPLETED,
        db_comment="Contribution lifecycle status for fundraise processing",
    )
    origin_fund_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_comment="Endaoment origin fund ID (DAF)",
    )
    destination_org_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_comment="Endaoment destination organization ID",
    )
    endaoment_transfer_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_comment="Endaoment grant transfer ID (external ID)",
    )

    class Meta:
        indexes = [
            models.Index(fields=["fundraise"]),
            models.Index(fields=["user"]),
        ]
