from decimal import Decimal

from django.db import models


class StakingUserSnapshot(models.Model):
    global_snapshot = models.ForeignKey(
        "reputation.StakingGlobalSnapshot",
        on_delete=models.CASCADE,
        related_name="user_snapshots",
    )
    user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="staking_user_snapshots",
    )
    stake_amount = models.DecimalField(
        max_digits=19, decimal_places=8, default=Decimal("0")
    )
    multiplier = models.DecimalField(
        max_digits=19, decimal_places=8, default=Decimal("1")
    )
    weighted_stake = models.DecimalField(
        max_digits=19, decimal_places=8, default=Decimal("0")
    )
    staking_opted_in_date = models.DateTimeField(null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "reputation"
        unique_together = [("global_snapshot", "user")]

    def __str__(self):
        return (
            f"StakingUserSnapshot(global_snapshot={self.global_snapshot_id}, "
            f"user={self.user_id}, stake={self.stake_amount})"
        )
