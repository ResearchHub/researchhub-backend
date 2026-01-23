from django.db import models

from utils.models import DefaultModel


class StakingSnapshot(DefaultModel):
    """
    Daily snapshot of a user's staking position for APY calculation.
    Captures RSC balance and the calculated multiplier based on holding duration.

    Used by the weekly distribution task to calculate each user's share of
    the staking reward pool.
    """

    user = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="staking_snapshots"
    )
    snapshot_date = models.DateField(db_index=True)

    # Balance at snapshot time
    rsc_balance = models.DecimalField(
        max_digits=19,
        decimal_places=10,
        help_text="User's RSC balance at snapshot time",
    )

    # Calculated multiplier based on time-weighted tiers
    multiplier = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Time-weighted multiplier (1.0x to 7.5x)",
    )

    # Weighted balance = rsc_balance * multiplier
    weighted_balance = models.DecimalField(
        max_digits=19,
        decimal_places=10,
        help_text="RSC balance multiplied by time-weighted multiplier",
    )

    class Meta:
        unique_together = ["user", "snapshot_date"]
        indexes = [
            models.Index(fields=["snapshot_date"]),
            models.Index(fields=["user", "snapshot_date"]),
        ]

    def __str__(self):
        return f"StakingSnapshot({self.user_id}, {self.snapshot_date}, {self.multiplier}x)"
