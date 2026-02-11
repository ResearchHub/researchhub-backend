from datetime import datetime, timedelta

from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
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

# Cache timeout for /leaderboard/me/ (1 hour).
LEADERBOARD_ME_CACHE_TIMEOUT = 60 * 60


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

    def _validate_and_parse_date_range(self, start_date, end_date):
        """
        Validate date-range params and parse to datetimes.
        Returns (error_response, start_dt, end_dt). If invalid, error_response is set.
        """
        if not (start_date and end_date):
            return (
                Response(
                    {
                        "error": "start_date and end_date are required when "
                        "period is not provided."
                    },
                    status=400,
                ),
                None,
                None,
            )
        is_valid, error_response = self._validate_date_range(start_date, end_date)
        if not is_valid:
            return error_response, None, None
        start_dt = timezone.make_aware(
            datetime.strptime(start_date, "%Y-%m-%d").replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        )
        end_dt = timezone.make_aware(
            datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
        )
        return None, start_dt, end_dt

    def _get_current_user_rank_and_data(
        self, leaderboard_type, period=None, start_dt=None, end_dt=None
    ):
        """
        Get current user's rank and data for leaderboard.
        Returns None if user is not authenticated or has no activity.

        Args:
            leaderboard_type: Either Leaderboard.EARNER or Leaderboard.FUNDER
            period: Pre-computed period constant (e.g., Leaderboard.SEVEN_DAYS) or None
            start_dt: Start datetime for custom date range (None if using pre-computed period)
            end_dt: End datetime for custom date range (None if using pre-computed period)

        Returns:
            dict: Serialized user data with rank and amount, or None
        """
        user = self.request.user
        if not user or not user.is_authenticated:
            return None

        excluded_ids = get_leaderboard_excluded_user_ids()
        if user.id in excluded_ids:
            return None

        if period is not None:
            try:
                entry = Leaderboard.objects.get(
                    user=user,
                    leaderboard_type=leaderboard_type,
                    period=period,
                )
                amount_label = (
                    "earned_rsc"
                    if leaderboard_type == Leaderboard.EARNER
                    else "total_funding"
                )
                return {
                    **self.serialize_user(user),
                    amount_label: entry.total_amount,
                    "rank": entry.rank,
                }
            except Leaderboard.DoesNotExist:
                return None

        if leaderboard_type == Leaderboard.EARNER:
            earner_source_types = [
                FundingActivity.TIP_REVIEW,
                FundingActivity.BOUNTY_PAYOUT,
            ]
            user_total_qs = FundingActivityRecipient.objects.filter(
                recipient_user=user,
                activity__activity_date__gte=start_dt,
                activity__activity_date__lte=end_dt,
                activity__source_type__in=earner_source_types,
            ).aggregate(total=Sum("amount"))
            user_total = user_total_qs["total"] or 0

            if user_total == 0:
                return None

            higher_count = (
                FundingActivityRecipient.objects.filter(
                    activity__activity_date__gte=start_dt,
                    activity__activity_date__lte=end_dt,
                    activity__source_type__in=earner_source_types,
                )
                .exclude(recipient_user_id__in=excluded_ids)
                .values("recipient_user_id")
                .annotate(total=Sum("amount"))
                .filter(total__gt=user_total)
                .count()
            )
            rank = higher_count + 1

            return {
                **self.serialize_user(user),
                "earned_rsc": user_total,
                "rank": rank,
            }
        else:  # FUNDER
            user_total_qs = FundingActivity.objects.filter(
                funder=user,
                activity_date__gte=start_dt,
                activity_date__lte=end_dt,
            ).aggregate(total=Sum("total_amount"))
            user_total = user_total_qs["total"] or 0

            if user_total == 0:
                return None

            higher_count = (
                FundingActivity.objects.filter(
                    activity_date__gte=start_dt,
                    activity_date__lte=end_dt,
                )
                .exclude(funder_id__in=excluded_ids)
                .values("funder_id")
                .annotate(total=Sum("total_amount"))
                .filter(total__gt=user_total)
                .count()
            )
            rank = higher_count + 1

            return {
                **self.serialize_user(user),
                "total_funding": user_total,
                "rank": rank,
            }

    @action(
        detail=False,
        methods=[RequestMethods.GET],
        permission_classes=[IsAuthenticated],
        url_path="me",
    )
    def me(self, request):
        """
        Returns the current user's leaderboard rank and data (reviewer and funder).
        Only for authenticated users. Optional: period (e.g. all_time, 30_days) or
        start_date & end_date for custom range. Default: all_time. Cached 1h per user.
        """
        cache_key = f"leaderboard:me:{request.user.id}:{request.get_full_path()}"
        data = cache.get(cache_key)
        if data is not None:
            return Response(data)

        period_str = request.GET.get("period")
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

        if period_str:
            leaderboard_period = self._map_period_to_leaderboard_period(period_str)
            if leaderboard_period:
                reviewer = self._get_current_user_rank_and_data(
                    Leaderboard.EARNER, period=leaderboard_period
                )
                funder = self._get_current_user_rank_and_data(
                    Leaderboard.FUNDER, period=leaderboard_period
                )
                data = {"reviewer": reviewer, "funder": funder}
                cache.set(cache_key, data, LEADERBOARD_ME_CACHE_TIMEOUT)
                return Response(data)

        if start_date and end_date:
            error_response, start_dt, end_dt = self._validate_and_parse_date_range(
                start_date, end_date
            )
            if error_response is not None:
                return error_response
            reviewer = self._get_current_user_rank_and_data(
                Leaderboard.EARNER, start_dt=start_dt, end_dt=end_dt
            )
            funder = self._get_current_user_rank_and_data(
                Leaderboard.FUNDER, start_dt=start_dt, end_dt=end_dt
            )
            data = {"reviewer": reviewer, "funder": funder}
            cache.set(cache_key, data, LEADERBOARD_ME_CACHE_TIMEOUT)
            return Response(data)

        # Default: all_time (e.g. for overview)
        reviewer = self._get_current_user_rank_and_data(
            Leaderboard.EARNER, period=Leaderboard.ALL_TIME
        )
        funder = self._get_current_user_rank_and_data(
            Leaderboard.FUNDER, period=Leaderboard.ALL_TIME
        )
        data = {"reviewer": reviewer, "funder": funder}
        cache.set(cache_key, data, LEADERBOARD_ME_CACHE_TIMEOUT)
        return Response(data)

    def _paginated_aggregated_response(
        self, aggregated_queryset, user_id_key, amount_label
    ):
        """
        Build paginated response from aggregated queryset (rows with user_id_key and total).
        amount_label is the key in each output item (e.g. "earned_rsc", "total_funding").
        """
        page = self.paginate_queryset(aggregated_queryset)
        if page is None:
            return Response([])

        page_number = self.paginator.page.number
        page_size = self.paginator.page_size
        starting_rank = (page_number - 1) * page_size + 1

        user_ids = [row[user_id_key] for row in page]
        users_by_id = {
            u.id: u
            for u in User.objects.filter(id__in=user_ids).select_related(
                "author_profile"
            )
        }
        totals_by_user = {row[user_id_key]: row["total"] for row in page}
        data = []
        for index, uid in enumerate(user_ids):
            user = users_by_id.get(uid)
            if not user:
                continue
            data.append(
                {
                    **self.serialize_user(user),
                    amount_label: totals_by_user[uid],
                    "rank": starting_rank + index,
                }
            )
        return self.get_paginated_response(data)

    @method_decorator(cache_page(60 * 60 * 6))
    @action(detail=False, methods=[RequestMethods.GET])
    def overview(self, request):
        """Returns top 5 users for each category (reviewers and funders), all-time."""
        reviewer_entries = (
            Leaderboard.objects.filter(
                leaderboard_type=Leaderboard.EARNER, period=Leaderboard.ALL_TIME
            )
            .select_related("user", "user__author_profile")
            .order_by("rank")[:5]
        )

        funder_entries = (
            Leaderboard.objects.filter(
                leaderboard_type=Leaderboard.FUNDER, period=Leaderboard.ALL_TIME
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
                        "rank": entry.rank,
                    }
                    for entry in reviewer_entries
                ],
                "funders": [
                    {
                        **self.serialize_user(entry.user),
                        "total_funding": entry.total_amount,
                        "rank": entry.rank,
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
                        "rank": entry.rank,
                    }
                    for entry in page
                ]
                return self.get_paginated_response(data)

        error_response, start_dt, end_dt = self._validate_and_parse_date_range(
            start_date, end_date
        )
        if error_response is not None:
            return error_response

        excluded_ids = get_leaderboard_excluded_user_ids()
        aggregated = (
            FundingActivityRecipient.objects.filter(
                activity__activity_date__gte=start_dt,
                activity__activity_date__lte=end_dt,
                activity__source_type__in=[
                    FundingActivity.TIP_REVIEW,
                    FundingActivity.BOUNTY_PAYOUT,
                ],
            )
            .exclude(recipient_user_id__in=excluded_ids)
            .values("recipient_user_id")
            .annotate(total=Sum("amount"))
            .order_by("-total")
        )

        page = self.paginate_queryset(aggregated)
        if page is None:
            return Response([])

        page_number = self.paginator.page.number
        page_size = self.paginator.page_size
        starting_rank = (page_number - 1) * page_size + 1

        user_ids = [row["recipient_user_id"] for row in page]
        users_by_id = {
            u.id: u
            for u in User.objects.filter(id__in=user_ids).select_related(
                "author_profile"
            )
        }
        totals_by_user = {row["recipient_user_id"]: row["total"] for row in page}
        data = []
        for index, uid in enumerate(user_ids):
            user = users_by_id.get(uid)
            if not user:
                continue
            data.append(
                {
                    **self.serialize_user(user),
                    "earned_rsc": totals_by_user[uid],
                    "rank": starting_rank + index,
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
                        "rank": entry.rank,
                    }
                    for entry in page
                ]
                return self.get_paginated_response(data)

        error_response, start_dt, end_dt = self._validate_and_parse_date_range(
            start_date, end_date
        )
        if error_response is not None:
            return error_response

        excluded_ids = get_leaderboard_excluded_user_ids()
        aggregated = (
            FundingActivity.objects.filter(
                activity_date__gte=start_dt,
                activity_date__lte=end_dt,
            )
            .exclude(funder_id__in=excluded_ids)
            .values("funder_id")
            .annotate(total=Sum("total_amount"))
            .order_by("-total")
        )

        page = self.paginate_queryset(aggregated)
        if page is None:
            return Response([])

        page_number = self.paginator.page.number
        page_size = self.paginator.page_size
        starting_rank = (page_number - 1) * page_size + 1

        user_ids = [row["funder_id"] for row in page]
        users_by_id = {
            u.id: u
            for u in User.objects.filter(id__in=user_ids).select_related(
                "author_profile"
            )
        }
        totals_by_user = {row["funder_id"]: row["total"] for row in page}
        data = []
        for index, uid in enumerate(user_ids):
            user = users_by_id.get(uid)
            if not user:
                continue
            data.append(
                {
                    **self.serialize_user(user),
                    "total_funding": totals_by_user[uid],
                    "rank": starting_rank + index,
                }
            )
        return self.get_paginated_response(data)
