from datetime import date as date_cls
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.related_models.staking_global_snapshot import StakingGlobalSnapshot
from reputation.related_models.staking_user_snapshot import StakingUserSnapshot
from reputation.related_models.staking_yield_record import StakingYieldRecord
from reputation.serializers.staking_yield_serializer import (
    StakingHistoryEntrySerializer,
    StakingStatsSerializer,
    StakingYieldDetailsSerializer,
    StakingYieldEarnedSinceSerializer,
)
from reputation.services.staking_yield_service import StakingYieldService

HISTORY_RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90, "all": None}

PUBLIC_CACHE_TIMEOUT = 60 * 60  # 1 hour; snapshots only update once a day
STATS_CACHE_KEY = "staking:public_stats:v1"
HISTORY_CACHE_KEY_PREFIX = "staking:public_history:v1"


class StakingYieldViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["GET"])
    def details(self, request):
        user = request.user

        latest_snapshot = (
            StakingUserSnapshot.objects.filter(user=user)
            .select_related("global_snapshot")
            .order_by("-global_snapshot__accrual_date")
            .first()
        )

        total_earned = StakingYieldRecord.objects.filter(
            user_snapshot__user=user
        ).aggregate(total=Sum("yield_amount"))["total"] or Decimal("0")

        global_snapshot = StakingGlobalSnapshot.load()
        apy = (
            StakingYieldService.compute_apy_for_snapshot(global_snapshot)
            if global_snapshot is not None
            else 0.0
        )

        balance_lots = StakingYieldService.get_balance_lot_details(
            user, timezone.now().date()
        )

        data = {
            "is_staking_opted_in": user.is_staking_opted_in,
            "staking_opted_in_date": user.staking_opted_in_date,
            "current_stake": (
                latest_snapshot.stake_amount if latest_snapshot else Decimal("0")
            ),
            "current_multiplier": (
                latest_snapshot.multiplier if latest_snapshot else Decimal("0")
            ),
            "current_weighted_stake": (
                latest_snapshot.weighted_stake if latest_snapshot else Decimal("0")
            ),
            "total_yield_earned": total_earned,
            "latest_accrual_date": (
                latest_snapshot.global_snapshot.accrual_date
                if latest_snapshot
                else None
            ),
            "apy": apy,
            "balance_lots": balance_lots,
        }
        serializer = StakingYieldDetailsSerializer(data)
        return Response(serializer.data)

    @action(detail=False, methods=["GET"])
    def earned_since(self, request):
        date_str = request.query_params.get("date")
        if not date_str:
            return Response(
                {"error": "Query parameter 'date' is required (YYYY-MM-DD)."},
                status=400,
            )

        try:
            since_date = date_cls.fromisoformat(date_str)
        except ValueError:
            return Response(
                {"error": "Invalid date format. Use YYYY-MM-DD."},
                status=400,
            )

        earned = StakingYieldRecord.objects.filter(
            user_snapshot__user=request.user,
            user_snapshot__global_snapshot__accrual_date__gte=since_date,
        ).aggregate(total=Sum("yield_amount"))["total"] or Decimal("0")

        data = {"since_date": since_date, "yield_earned": earned}
        serializer = StakingYieldEarnedSinceSerializer(data)
        return Response(serializer.data)

    @action(detail=False, methods=["GET"], permission_classes=[AllowAny])
    def stats(self, request):
        cached = cache.get(STATS_CACHE_KEY)
        if cached is not None:
            return Response(cached)

        payload = self._build_stats_payload()
        data = StakingStatsSerializer(payload).data
        cache.set(STATS_CACHE_KEY, data, timeout=PUBLIC_CACHE_TIMEOUT)
        return Response(data)

    @action(detail=False, methods=["GET"], permission_classes=[AllowAny])
    def history(self, request):
        range_param = request.query_params.get("range", "90d")
        if range_param not in HISTORY_RANGE_DAYS:
            return Response(
                {
                    "error": (
                        "Invalid range. Must be one of: "
                        f"{', '.join(HISTORY_RANGE_DAYS.keys())}."
                    )
                },
                status=400,
            )

        cache_key = HISTORY_CACHE_KEY_PREFIX + ":" + range_param
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        days = HISTORY_RANGE_DAYS[range_param]
        if days is None:
            start_date = None
        else:
            start_date = date_cls.today() - timedelta(days=days)

        rows = StakingYieldService.build_history(start_date=start_date, end_date=None)
        data = {
            "range": range_param,
            "results": StakingHistoryEntrySerializer(rows, many=True).data,
        }
        cache.set(cache_key, data, timeout=PUBLIC_CACHE_TIMEOUT)
        return Response(data)

    def _build_stats_payload(self):
        latest = StakingGlobalSnapshot.load()
        if latest is None:
            return {
                "accrual_date": None,
                "apy": 0.0,
                "apy_30d_avg": 0.0,
                "holders": 0,
                "top_10_concentration_pct": 0.0,
                "total_staked_rsc": Decimal("0"),
                "total_value_locked_usd": None,
                "circulating_supply_rsc": Decimal("0"),
                "pct_of_supply_staked": 0.0,
            }

        recent_snapshots = list(
            StakingGlobalSnapshot.objects.order_by("-accrual_date")[:30]
        )
        apy_values = [
            StakingYieldService.compute_apy_for_snapshot(s) for s in recent_snapshots
        ]
        apy_30d_avg = sum(apy_values) / len(apy_values) if apy_values else 0.0

        try:
            usd_rate = RscExchangeRate.get_latest()
        except AttributeError:
            usd_rate = None
        if usd_rate:
            tvl_usd = Decimal(str(usd_rate)) * latest.total_staked
        else:
            tvl_usd = None

        if latest.circulating_supply > 0:
            pct_of_supply = (
                float(latest.total_staked) / float(latest.circulating_supply) * 100
            )
        else:
            pct_of_supply = 0.0

        return {
            "accrual_date": latest.accrual_date,
            "apy": StakingYieldService.compute_apy_for_snapshot(latest),
            "apy_30d_avg": apy_30d_avg,
            "holders": StakingYieldService.holders_count(latest),
            "top_10_concentration_pct": (
                StakingYieldService.compute_top_n_pct_concentration(latest, pct=10)
            ),
            "total_staked_rsc": latest.total_staked,
            "total_value_locked_usd": tvl_usd,
            "circulating_supply_rsc": latest.circulating_supply,
            "pct_of_supply_staked": pct_of_supply,
        }
