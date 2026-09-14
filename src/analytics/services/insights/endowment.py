from decimal import Decimal

from django.db.models import DecimalField, Sum
from django.db.models.functions import Cast, Coalesce

from purchase.models import Balance
from reputation.models import StakingGlobalSnapshot, StakingYieldRecord
from reputation.services.staking_yield_service import StakingYieldService

AMOUNT_FIELD = DecimalField(max_digits=30, decimal_places=10)


def _sum_balances(queryset):
    return queryset.annotate(decimal_amount=Cast("amount", AMOUNT_FIELD)).aggregate(
        total=Coalesce(Sum("decimal_amount"), Decimal(0))
    )["total"]


def get_endowment_metrics(period):
    latest = StakingGlobalSnapshot.objects.order_by("-accrual_date").first()
    yield_earners = StakingYieldRecord.objects.filter(
        yield_amount__gt=0,
        created_date__gte=period.start,
        created_date__lt=period.end,
    )

    credits = Balance.objects.filter(
        is_locked=True,
        lock_type=Balance.LockType.FUNDING_CREDIT,
    )

    if latest is None:
        current_yield_apy_percent = 0
        tvl_rsc = Decimal(0)
        accrual_date = None
    else:
        current_yield_apy_percent = StakingYieldService.compute_apy_for_snapshot(latest)
        tvl_rsc = latest.total_staked
        accrual_date = latest.accrual_date

    return {
        "as_of": accrual_date,
        "current_yield_apy_percent": current_yield_apy_percent,
        "tvl_rsc": tvl_rsc,
        "funding_credits_ready_rsc": _sum_balances(credits),
        "unique_earners": (
            yield_earners.values("user_snapshot__user_id").distinct().count()
        ),
    }
