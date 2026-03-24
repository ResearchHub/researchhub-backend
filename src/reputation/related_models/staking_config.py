from decimal import Decimal

from django.db import models


class StakingConfig(models.Model):
    emission_per_year = models.DecimalField(
        max_digits=19, decimal_places=8, default=Decimal("0")
    )
    circulating_supply = models.DecimalField(
        max_digits=19, decimal_places=8, default=Decimal("0")
    )
    staked_fraction = models.DecimalField(
        max_digits=19, decimal_places=18, default=Decimal("0")
    )
    avg_multiplier = models.DecimalField(
        max_digits=19, decimal_places=8, default=Decimal("1")
    )
    is_active = models.BooleanField(default=False)
    last_circulating_supply_at = models.DateTimeField(null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "reputation"

    def __str__(self):
        return f"StakingConfig(pk={self.pk}, active={self.is_active})"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
