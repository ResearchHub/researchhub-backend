from decimal import Decimal

from django.db import models


class StakingYieldRecord(models.Model):
    user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="staking_yield_records",
    )
    accrual_date = models.DateField()
    stake_amount = models.DecimalField(
        max_digits=19, decimal_places=8, default=Decimal("0")
    )
    annualized_rate = models.DecimalField(
        max_digits=19, decimal_places=8, default=Decimal("0")
    )
    proration_fraction = models.DecimalField(
        max_digits=19, decimal_places=18, default=Decimal("1")
    )
    yield_amount = models.DecimalField(
        max_digits=19, decimal_places=8, default=Decimal("0")
    )
    global_snapshot = models.ForeignKey(
        "reputation.StakingGlobalSnapshot",
        on_delete=models.PROTECT,
        related_name="yield_records",
    )
    user_snapshot = models.ForeignKey(
        "reputation.StakingUserSnapshot",
        on_delete=models.PROTECT,
        related_name="yield_records",
    )
    distribution = models.OneToOneField(
        "reputation.Distribution",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staking_yield_record",
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "reputation"
        unique_together = [("user", "accrual_date")]

    def __str__(self):
        return (
            f"StakingYieldRecord(user={self.user_id}, "
            f"date={self.accrual_date}, yield={self.yield_amount})"
        )
