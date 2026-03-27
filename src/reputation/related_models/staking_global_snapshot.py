from decimal import Decimal

from django.db import models

from utils.models import DefaultModel


class StakingGlobalSnapshot(DefaultModel):
    accrual_date = models.DateField(unique=True)
    emission_per_year = models.DecimalField(
        max_digits=19, decimal_places=8, default=Decimal("0")
    )
    circulating_supply = models.DecimalField(
        max_digits=19, decimal_places=8, default=Decimal("0")
    )
    total_staked = models.DecimalField(
        max_digits=19, decimal_places=8, default=Decimal("0")
    )
    total_weighted_stake = models.DecimalField(
        max_digits=19, decimal_places=8, default=Decimal("0")
    )

    class Meta:
        app_label = "reputation"

    def __str__(self):
        return (
            f"StakingGlobalSnapshot(pk={self.pk}, " f"accrual_date={self.accrual_date})"
        )

    @classmethod
    def load(cls):
        return cls.objects.order_by("-accrual_date").first()

    @classmethod
    def load_for_accrual_date(cls, accrual_date):
        return cls.objects.filter(accrual_date=accrual_date).first()
