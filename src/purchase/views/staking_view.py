from datetime import timedelta

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from purchase.models import FundingCredit, StakingDistributionRecord, StakingSnapshot
from purchase.serializers.staking_serializer import (
    FundingCreditBalanceSerializer,
    FundingCreditSerializer,
    StakingDistributionRecordSerializer,
    StakingHistorySerializer,
    StakingInfoSerializer,
    StakingSnapshotSerializer,
)
from purchase.services.funding_credit_service import FundingCreditService
from purchase.services.staking_service import StakingService
from utils.throttles import THROTTLE_CLASSES


class StakingViewSet(viewsets.ViewSet):
    """
    API endpoints for staking information and funding credits.

    The staking system automatically rewards RSC holders with non-liquid
    funding credits based on their holding duration. These credits can
    only be spent on funding research proposals.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = THROTTLE_CLASSES

    @action(detail=False, methods=["GET"])
    def info(self, request):
        """
        Get current staking information for the authenticated user.

        Returns:
            - rsc_balance: Current RSC balance
            - weighted_balance: Balance with multiplier applied
            - current_multiplier: Current time-weighted multiplier
            - multiplier_tier: Current tier name (Bronze, Silver, etc.)
            - days_held: Days since oldest RSC entered account
            - days_until_next_tier: Days until next multiplier tier
            - projected_weekly_credits: Estimated weekly funding credits
            - projected_apy: Estimated annual percentage yield
        """
        user = request.user
        staking_service = StakingService()
        staking_info = staking_service.get_user_staking_info(user)

        serializer = StakingInfoSerializer(staking_info)
        return Response(serializer.data)

    @action(detail=False, methods=["GET"])
    def funding_credits(self, request):
        """
        Get funding credit balance and recent transactions.

        Returns:
            - balance: Total funding credits available
            - recent_transactions: Last 20 credit transactions
        """
        user = request.user
        funding_credit_service = FundingCreditService()

        balance = funding_credit_service.get_user_balance(user)
        recent_transactions = funding_credit_service.get_recent_transactions(
            user, limit=20
        )

        data = {
            "balance": balance,
            "recent_transactions": recent_transactions,
        }

        serializer = FundingCreditBalanceSerializer(data)
        return Response(serializer.data)

    @action(detail=False, methods=["GET"])
    def history(self, request):
        """
        Get staking history (snapshots and distributions).

        Query params:
            - days: Number of days to look back (default: 30, max: 365)

        Returns:
            - snapshots: Daily snapshot history
            - distributions: Reward distribution history
        """
        user = request.user

        # Parse days parameter
        try:
            days = int(request.query_params.get("days", 30))
            days = min(max(days, 1), 365)  # Clamp between 1 and 365
        except ValueError:
            days = 30

        from django.utils import timezone

        start_date = timezone.now().date() - timedelta(days=days)

        snapshots = StakingSnapshot.objects.filter(
            user=user,
            snapshot_date__gte=start_date,
        ).order_by("-snapshot_date")[:days]

        # Get distributions the user participated in
        # by checking if they have snapshots for those dates
        snapshot_dates = snapshots.values_list("snapshot_date", flat=True)
        distributions = StakingDistributionRecord.objects.filter(
            distribution_date__gte=start_date,
            status=StakingDistributionRecord.Status.COMPLETED,
        ).order_by("-distribution_date")

        data = {
            "snapshots": snapshots,
            "distributions": distributions,
        }

        serializer = StakingHistorySerializer(data)
        return Response(serializer.data)

    @action(detail=False, methods=["GET"])
    def transactions(self, request):
        """
        Get paginated funding credit transactions.

        Query params:
            - page: Page number (default: 1)
            - page_size: Items per page (default: 20, max: 100)

        Returns:
            Paginated list of funding credit transactions
        """
        user = request.user

        queryset = FundingCredit.objects.filter(user=user).order_by("-created_date")

        paginator = PageNumberPagination()
        paginator.page_size = min(
            int(request.query_params.get("page_size", 20)), 100
        )

        page = paginator.paginate_queryset(queryset, request)
        serializer = FundingCreditSerializer(page, many=True)

        return paginator.get_paginated_response(serializer.data)
