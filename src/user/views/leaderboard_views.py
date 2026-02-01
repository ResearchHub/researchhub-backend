from datetime import datetime, timedelta

from django.db.models import Sum
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from user.models import User
from user.related_models.funding_activity_model import (
    FundingActivity,
    FundingActivityRecipient,
)
from user.related_models.leaderboard_model import Leaderboard
from user.serializers import DynamicUserSerializer
from user.services.funding_activity_service import get_leaderboard_excluded_user_ids
from utils.http import RequestMethods

# Maximum allowed date range (in days) when querying leaderboard by start_date/end_date.
MAX_DATE_RANGE_DAYS = 60


class LeaderboardPagination(PageNumberPagination):
    """
    Pagination class for leaderboard endpoints.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class LeaderboardViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    pagination_class = LeaderboardPagination

    @property
    def user_serializer_config(self):
        """
        Returns the configuration for DynamicUserSerializer.
        This ensures consistent user serialization across all endpoints.
        """
        return {
            "context": {
                "request": self.request,
                "usr_dus_get_author_profile": {
                    "_include_fields": [
                        "first_name",
                        "last_name",
                        "created_date",
                        "profile_image",
                        "headline",
                        "id",
                        "user",
                    ]
                },
            },
            "fields": [
                "id",
                "first_name",
                "last_name",
                "created_date",
                "author_profile",
                "is_verified",
            ],
        }

    def serialize_user(self, user):
        """
        Helper method to serialize a user with consistent configuration.
        """
        config = self.user_serializer_config
        return DynamicUserSerializer(
            user, context=config["context"], _include_fields=config["fields"]
        ).data

    def _map_period_to_leaderboard_period(self, period_str):
        """
        Map period query param to Leaderboard period constant.
        Returns None if period doesn't match a pre-computed period.
        """
        period_map = {
            "7_days": Leaderboard.SEVEN_DAYS,
            "30_days": Leaderboard.THIRTY_DAYS,
            "6_months": Leaderboard.SIX_MONTHS,
            "1_year": Leaderboard.ONE_YEAR,
            "all_time": Leaderboard.ALL_TIME,
        }
        return period_map.get(period_str.lower())

    def _validate_date_range(self, start_date, end_date, max_days=MAX_DATE_RANGE_DAYS):
        """
        Validates that the date range doesn't exceed the maximum allowed days.

        Args:
            start_date: Start date string in ISO format
            end_date: End date string in ISO format
            max_days: Maximum allowed days between dates (default: MAX_DATE_RANGE_DAYS)

        Returns:
            tuple: (is_valid, error_response)
                - is_valid: Boolean indicating if the range is valid
                - error_response: Response object with error details if invalid, None otherwise
        """
        if not (start_date and end_date):
            return True, None

        try:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()

            delta_days = (end_date_obj - start_date_obj).days

            if delta_days > max_days:
                error_msg = f"Date range exceeds {max_days} days"
                return False, Response({"error": error_msg}, status=400)
            return True, None
        except (ValueError, TypeError):
            return False, Response(
                {"error": "Invalid date format. Use ISO format (YYYY-MM-DD)."},
                status=400,
            )

    @method_decorator(cache_page(60 * 60 * 6))
    @action(detail=False, methods=[RequestMethods.GET])
    def overview(self, request):
        """Returns top 5 users for each category (reviewers and funders)"""
        # Use pre-computed leaderboard for reviewers (7 days) and funders (30 days)
        reviewer_entries = (
            Leaderboard.objects.filter(
                leaderboard_type=Leaderboard.EARNER, period=Leaderboard.SEVEN_DAYS
            )
            .select_related("user", "user__author_profile")
            .order_by("rank")[:5]
        )

        funder_entries = (
            Leaderboard.objects.filter(
                leaderboard_type=Leaderboard.FUNDER, period=Leaderboard.THIRTY_DAYS
            )
            .select_related("user", "user__author_profile")
            .order_by("rank")[:5]
        )

        return Response(
            {
                "reviewers": [
                    {
                        **self.serialize_user(entry.user),
                        "earned_rsc": entry.total_amount,
                    }
                    for entry in reviewer_entries
                ],
                "funders": [
                    {
                        **self.serialize_user(entry.user),
                        "total_funding": entry.total_amount,
                    }
                    for entry in funder_entries
                ],
            }
        )

    @method_decorator(cache_page(60 * 60 * 6))
    @action(detail=False, methods=[RequestMethods.GET])
    def reviewers(self, request):
        """Returns top reviewers for a given time period"""
        period_str = request.GET.get("period")
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

        # If period is provided and matches a pre-computed period, use Leaderboard table
        if period_str:
            leaderboard_period = self._map_period_to_leaderboard_period(period_str)
            if leaderboard_period:
                leaderboard_entries = (
                    Leaderboard.objects.filter(
                        leaderboard_type=Leaderboard.EARNER, period=leaderboard_period
                    )
                    .select_related("user", "user__author_profile")
                    .order_by("rank")
                )

                page = self.paginate_queryset(leaderboard_entries)
                if page is None:
                    return Response([])

                data = [
                    {
                        **self.serialize_user(entry.user),
                        "earned_rsc": entry.total_amount,
                    }
                    for entry in page
                ]
                return self.get_paginated_response(data)

        if not (start_date and end_date):
            return Response(
                {
                    "error": "start_date and end_date are required when period is not provided."
                },
                status=400,
            )
        is_valid, error_response = self._validate_date_range(start_date, end_date)
        if not is_valid:
            return error_response

        excluded_ids = get_leaderboard_excluded_user_ids()
        start_dt = timezone.make_aware(
            datetime.strptime(start_date, "%Y-%m-%d").replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        )
        end_dt = timezone.make_aware(
            datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        ) + timedelta(days=1)

        aggregated = (
            FundingActivityRecipient.objects.filter(
                activity__activity_date__gte=start_dt,
                activity__activity_date__lt=end_dt,
            )
            .exclude(recipient_user_id__in=excluded_ids)
            .values("recipient_user_id")
            .annotate(total=Sum("amount"))
            .order_by("-total")
        )

        page = self.paginate_queryset(aggregated)
        if page is None:
            return Response([])
        user_ids = [row["recipient_user_id"] for row in page]
        users_by_id = {
            u.id: u
            for u in User.objects.filter(id__in=user_ids).select_related(
                "author_profile"
            )
        }
        totals_by_user = {row["recipient_user_id"]: row["total"] for row in page}
        data = []
        for uid in user_ids:
            user = users_by_id.get(uid)
            if not user:
                continue
            data.append(
                {
                    **self.serialize_user(user),
                    "earned_rsc": totals_by_user[uid],
                }
            )
        return self.get_paginated_response(data)

    @method_decorator(cache_page(60 * 60 * 6))
    @action(detail=False, methods=[RequestMethods.GET])
    def funders(self, request):
        """Returns top funders for a given time period"""
        period_str = request.GET.get("period")
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

        # If period is provided and matches a pre-computed period, use Leaderboard table
        if period_str:
            leaderboard_period = self._map_period_to_leaderboard_period(period_str)
            if leaderboard_period:
                leaderboard_entries = (
                    Leaderboard.objects.filter(
                        leaderboard_type=Leaderboard.FUNDER, period=leaderboard_period
                    )
                    .select_related("user", "user__author_profile")
                    .order_by("rank")
                )

                page = self.paginate_queryset(leaderboard_entries)
                if page is None:
                    return Response([])

                data = [
                    {
                        **self.serialize_user(entry.user),
                        "total_funding": entry.total_amount,
                    }
                    for entry in page
                ]
                return self.get_paginated_response(data)

        if not (start_date and end_date):
            return Response(
                {
                    "error": "start_date and end_date are required when period is not provided."
                },
                status=400,
            )
        is_valid, error_response = self._validate_date_range(start_date, end_date)
        if not is_valid:
            return error_response

        excluded_ids = get_leaderboard_excluded_user_ids()
        start_dt = timezone.make_aware(
            datetime.strptime(start_date, "%Y-%m-%d").replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        )
        end_dt = timezone.make_aware(
            datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        ) + timedelta(days=1)

        aggregated = (
            FundingActivity.objects.filter(
                activity_date__gte=start_dt,
                activity_date__lt=end_dt,
            )
            .exclude(funder_id__in=excluded_ids)
            .values("funder_id")
            .annotate(total=Sum("total_amount"))
            .order_by("-total")
        )

        page = self.paginate_queryset(aggregated)
        if page is None:
            return Response([])
        user_ids = [row["funder_id"] for row in page]
        users_by_id = {
            u.id: u
            for u in User.objects.filter(id__in=user_ids).select_related(
                "author_profile"
            )
        }
        totals_by_user = {row["funder_id"]: row["total"] for row in page}
        data = []
        for uid in user_ids:
            user = users_by_id.get(uid)
            if not user:
                continue
            data.append(
                {
                    **self.serialize_user(user),
                    "total_funding": totals_by_user[uid],
                }
            )
        return self.get_paginated_response(data)
