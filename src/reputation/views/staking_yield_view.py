from datetime import date as date_cls
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from reputation.related_models.staking_global_snapshot import StakingGlobalSnapshot
from reputation.related_models.staking_user_snapshot import StakingUserSnapshot
from reputation.related_models.staking_yield_record import StakingYieldRecord
from reputation.serializers.staking_yield_serializer import (
    StakingYieldDetailsSerializer,
    StakingYieldEarnedSinceSerializer,
)
from reputation.services.staking_yield_service import StakingYieldService


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
        if global_snapshot and global_snapshot.total_staked > 0:
            daily_emission = StakingYieldService.compute_total_daily_emission(
                global_snapshot.accrual_date
            )
            apy = (
                float(daily_emission) / float(global_snapshot.total_staked) * 365 * 100
            )
        else:
            apy = 0.0

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
