from django.contrib import admin

from reputation.related_models.staking_config import StakingConfig
from reputation.related_models.staking_yield_accrual import StakingYieldAccrual


@admin.register(StakingConfig)
class StakingConfigAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "emission_per_year",
        "circulating_supply",
        "staked_fraction",
        "is_active",
        "updated_date",
    )


@admin.register(StakingYieldAccrual)
class StakingYieldAccrualAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "user",
        "accrual_date",
        "stake_amount",
        "apy",
        "yield_amount",
        "distribution",
    )
    list_filter = ("accrual_date",)
    raw_id_fields = ("user", "distribution")
