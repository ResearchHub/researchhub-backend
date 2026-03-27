from decimal import Decimal

from django.db import models

from utils.models import DefaultModel


class StakingYieldRecord(DefaultModel):
    annualized_rate = models.DecimalField(
        max_digits=19, decimal_places=8, default=Decimal("0")
    )
    proration_fraction = models.DecimalField(
        max_digits=19, decimal_places=18, default=Decimal("1")
    )
    yield_amount = models.DecimalField(
        max_digits=19, decimal_places=8, default=Decimal("0")
    )
    user_snapshot = models.OneToOneField(
        "reputation.StakingUserSnapshot",
        on_delete=models.PROTECT,
        related_name="yield_record",
    )
    distribution = models.OneToOneField(
        "reputation.Distribution",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staking_yield_record",
    )

    class Meta:
        app_label = "reputation"

    def __str__(self):
        return f"StakingYieldRecord(user_snapshot={self.user_snapshot_id}, yield={self.yield_amount})"
