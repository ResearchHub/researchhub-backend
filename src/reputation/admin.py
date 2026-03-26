from django.contrib import admin

from reputation.related_models.staking_snapshot import StakingSnapshot
from reputation.related_models.staking_yield_accrual import StakingYieldAccrual


@admin.register(StakingSnapshot)
class StakingSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "emission_per_year",
        "circulating_supply",
        "staked_fraction",
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
