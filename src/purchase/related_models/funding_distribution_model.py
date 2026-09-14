from django.db import models

from utils.models import DefaultModel


class FundingDistribution(DefaultModel):
    """Record of RSC moved from a FundingPool into a proposal Fundraise.

    Used to detect pool-sourced escrow slices on fundraise close/complete so
    those amounts return to the pool (or settle) instead of a user wallet.
    """

    APPLIED = "APPLIED"
    REVERSED = "REVERSED"
    SETTLED = "SETTLED"
    STATUS_CHOICES = (
        (APPLIED, APPLIED),
        (REVERSED, REVERSED),
        (SETTLED, SETTLED),
    )

    pool = models.ForeignKey(
        "purchase.FundingPool",
        on_delete=models.CASCADE,
        related_name="distributions",
        db_comment="Pool the funds were drawn from",
    )
    distributed_by = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="funding_distributions",
        db_comment="User who performed the distribution (audit only; no wallet debit)",
    )
    amount = models.DecimalField(
        decimal_places=10,
        max_digits=19,
        db_comment="RSC amount moved from the pool into the proposal fundraise",
    )
    application = models.ForeignKey(
        "purchase.GrantApplication",
        on_delete=models.CASCADE,
        related_name="funding_distributions",
        db_comment="Grant application whose proposal fundraise was topped up",
    )
    target_fundraise = models.ForeignKey(
        "purchase.Fundraise",
        on_delete=models.CASCADE,
        related_name="funding_distributions",
        db_comment="Proposal fundraise that received the pool top-up",
    )
    fundraise_purchase = models.OneToOneField(
        "purchase.Purchase",
        on_delete=models.CASCADE,
        related_name="funding_distribution",
        db_comment=(
            "Audit Purchase on the proposal fundraise; identifies pool-sourced "
            "slices on close/complete"
        ),
    )
    status = models.CharField(
        choices=STATUS_CHOICES,
        default=APPLIED,
        max_length=32,
        db_comment="APPLIED while in escrow; REVERSED on close; SETTLED on complete",
    )

    class Meta:
        indexes = [
            models.Index(fields=["pool", "status"], name="purchase_fu_pool_status_idx"),
            models.Index(
                fields=["target_fundraise", "status"],
                name="purchase_fu_tfund_status_idx",
            ),
            models.Index(fields=["status"], name="purchase_fu_status_dist_idx"),
        ]

    def __str__(self):
        return (
            f"FundingDistribution(pool={self.pool_id}, "
            f"amount={self.amount}, status={self.status})"
        )
