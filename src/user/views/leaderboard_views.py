from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import DecimalField, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from purchase.models import Purchase
from reputation.models import Bounty, Distribution
from reputation.related_models.escrow import Escrow, EscrowRecipients
from researchhub_comment.constants.rh_comment_thread_types import (
    COMMUNITY_REVIEW,
    PEER_REVIEW,
)
from researchhub_comment.models import RhCommentModel
from user.management.commands.setup_bank_user import BANK_EMAIL
from user.models import User
from user.related_models.funding_activity_model import (
    FundingActivity,
    FundingActivityRecipient,
)
from user.related_models.leaderboard_model import Leaderboard
from user.related_models.user_model import FOUNDATION_EMAIL
from user.serializers import DynamicUserSerializer
from utils.http import RequestMethods


class LeaderboardPagination(PageNumberPagination):
    """
    Pagination class for leaderboard endpoints.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class LeaderboardViewSet(viewsets.ModelViewSet):
    queryset = User.objects.filter(
        is_active=True,
        is_suspended=False,
        probable_spammer=False,
    ).exclude(
        email__in=[
            BANK_EMAIL,  # Exclude bank user from leaderboards
            FOUNDATION_EMAIL,  # Exclude foundation account from leaderboards
        ]
    )
    permission_classes = [AllowAny]
    pagination_class = LeaderboardPagination

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.purchase_content_type = ContentType.objects.get_for_model(Purchase)
        self.comment_content_type = ContentType.objects.get_for_model(RhCommentModel)

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

    def get_queryset(self):
        return self.queryset.select_related("author_profile")

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

    def _get_period_date_range(self, period):
        """Get start_date and end_date for a Leaderboard period."""
        now = timezone.now()
        if period == Leaderboard.SEVEN_DAYS:
            return now - timedelta(days=7), now
        elif period == Leaderboard.THIRTY_DAYS:
            return now - timedelta(days=30), now
        elif period == Leaderboard.SIX_MONTHS:
            return now - timedelta(days=180), now
        elif period == Leaderboard.ONE_YEAR:
            return now - timedelta(days=365), now
        elif period == Leaderboard.ALL_TIME:
            return None, now
        return None, now

    def _get_reviewer_breakdowns_from_funding_activity(
        self, user_ids, start_date=None, end_date=None
    ):
        """
        Get breakdown of bounty_earnings and tip_earnings from FundingActivity
        for the given users and date range.
        """
        # Bounty earnings: BOUNTY_PAYOUT recipients
        bounty_qs = FundingActivityRecipient.objects.filter(
            recipient_user_id__in=user_ids,
            activity__source_type=FundingActivity.BOUNTY_PAYOUT,
        )
        if start_date:
            bounty_qs = bounty_qs.filter(
                activity__activity_date__gte=start_date,
                activity__activity_date__lte=end_date,
            )

        # Tip earnings: TIP_REVIEW recipients
        tip_qs = FundingActivityRecipient.objects.filter(
            recipient_user_id__in=user_ids,
            activity__source_type=FundingActivity.TIP_REVIEW,
        )
        if start_date:
            tip_qs = tip_qs.filter(
                activity__activity_date__gte=start_date,
                activity__activity_date__lte=end_date,
            )

        bounty_totals = {
            entry["recipient_user_id"]: entry["total"]
            for entry in bounty_qs.values("recipient_user_id")
            .annotate(total=Sum("amount"))
            .values("recipient_user_id", "total")
        }

        tip_totals = {
            entry["recipient_user_id"]: entry["total"]
            for entry in tip_qs.values("recipient_user_id")
            .annotate(total=Sum("amount"))
            .values("recipient_user_id", "total")
        }

        breakdowns = {}
        for user_id in user_ids:
            breakdowns[user_id] = {
                "bounty_earnings": Decimal(str(bounty_totals.get(user_id, 0))),
                "tip_earnings": Decimal(str(tip_totals.get(user_id, 0))),
            }
        return breakdowns

    def _get_funder_breakdowns_from_funding_activity(
        self, user_ids, start_date=None, end_date=None
    ):
        """
        Get breakdown of purchase_funding, bounty_funding, and distribution_funding
        from FundingActivity for the given users and date range.
        """
        # Purchase funding: FUNDRAISE_PAYOUT + TIP_DOCUMENT
        purchase_qs = FundingActivity.objects.filter(
            funder_id__in=user_ids,
            source_type__in=[
                FundingActivity.FUNDRAISE_PAYOUT,
                FundingActivity.TIP_DOCUMENT,
            ],
        )
        if start_date:
            purchase_qs = purchase_qs.filter(
                activity_date__gte=start_date, activity_date__lte=end_date
            )

        # Bounty funding: BOUNTY_PAYOUT (funder is the bounty creator)
        bounty_qs = FundingActivity.objects.filter(
            funder_id__in=user_ids, source_type=FundingActivity.BOUNTY_PAYOUT
        )
        if start_date:
            bounty_qs = bounty_qs.filter(
                activity_date__gte=start_date, activity_date__lte=end_date
            )

        # Distribution funding: FEE
        distribution_qs = FundingActivity.objects.filter(
            funder_id__in=user_ids, source_type=FundingActivity.FEE
        )
        if start_date:
            distribution_qs = distribution_qs.filter(
                activity_date__gte=start_date, activity_date__lte=end_date
            )

        purchase_totals = {
            entry["funder_id"]: entry["total"]
            for entry in purchase_qs.values("funder_id")
            .annotate(total=Sum("total_amount"))
            .values("funder_id", "total")
        }

        bounty_totals = {
            entry["funder_id"]: entry["total"]
            for entry in bounty_qs.values("funder_id")
            .annotate(total=Sum("total_amount"))
            .values("funder_id", "total")
        }

        distribution_totals = {
            entry["funder_id"]: entry["total"]
            for entry in distribution_qs.values("funder_id")
            .annotate(total=Sum("total_amount"))
            .values("funder_id", "total")
        }

        breakdowns = {}
        for user_id in user_ids:
            breakdowns[user_id] = {
                "purchase_funding": Decimal(str(purchase_totals.get(user_id, 0))),
                "bounty_funding": Decimal(str(bounty_totals.get(user_id, 0))),
                "distribution_funding": Decimal(
                    str(distribution_totals.get(user_id, 0))
                ),
            }
        return breakdowns

    def _get_reviewer_bounty_conditions(self, start_date=None, end_date=None):
        conditions = {
            "user_id": OuterRef("pk"),
            "escrow__status": Escrow.PAID,
            "escrow__hold_type": Escrow.BOUNTY,
            "escrow__bounties__bounty_type": Bounty.Type.REVIEW,
            "escrow__bounties__solutions__rh_comment__comment_type__in": [
                PEER_REVIEW,
                COMMUNITY_REVIEW,
            ],
        }

        if start_date:
            conditions["created_date__gte"] = start_date
        if end_date:
            conditions["created_date__lte"] = end_date

        return conditions

    def _get_reviewer_tips_conditions(self, start_date=None, end_date=None):
        conditions = {
            "recipient_id": OuterRef("pk"),
            "distribution_type": "PURCHASE",
            "proof_item_content_type": self.purchase_content_type,
            "proof_item_object_id__in": Purchase.objects.filter(
                content_type_id=self.comment_content_type.id,
                paid_status="PAID",
                rh_comments__comment_type__in=[PEER_REVIEW, COMMUNITY_REVIEW],
            ).values("id"),
        }

        if start_date:
            conditions["created_date__gte"] = start_date
        if end_date:
            conditions["created_date__lte"] = end_date

        return conditions

    def _get_funder_purchase_conditions(self, start_date=None, end_date=None):
        conditions = {
            "user_id": OuterRef("pk"),
            "paid_status": Purchase.PAID,
            "purchase_type__in": [Purchase.FUNDRAISE_CONTRIBUTION, Purchase.BOOST],
        }

        if start_date:
            conditions["created_date__gte"] = start_date
        if end_date:
            conditions["created_date__lte"] = end_date

        return conditions

    def _get_funder_bounty_conditions(self, start_date=None, end_date=None):
        conditions = {
            "created_by_id": OuterRef("pk"),
        }

        if start_date:
            conditions["created_date__gte"] = start_date
        if end_date:
            conditions["created_date__lte"] = end_date

        return conditions

    def _get_funder_distribution_conditions(self, start_date=None, end_date=None):
        conditions = {
            "giver_id": OuterRef("pk"),
            "distribution_type__in": [
                "BOUNTY_DAO_FEE",
                "BOUNTY_RH_FEE",
                "SUPPORT_RH_FEE",
            ],
        }

        if start_date:
            conditions["created_date__gte"] = start_date
        if end_date:
            conditions["created_date__lte"] = end_date

        return conditions

    def _create_reviewer_earnings_annotation(self, start_date=None, end_date=None):
        """
        Creates annotation dictionary for reviewer earnings calculations

        Args:
            start_date: Optional start date for filtering
            end_date: Optional end date for filtering
        Returns:
            Dictionary of annotations for bounty_earnings, tip_earnings, and earned_rsc
        """
        bounty_conditions = self._get_reviewer_bounty_conditions(start_date, end_date)
        tips_conditions = self._get_reviewer_tips_conditions(start_date, end_date)

        return {
            "bounty_earnings": Coalesce(
                Subquery(
                    EscrowRecipients.objects.filter(**bounty_conditions)
                    .values("user_id")
                    .annotate(total=Sum("amount"))
                    .values("total"),
                    output_field=DecimalField(max_digits=19, decimal_places=8),
                ),
                Value(0, output_field=DecimalField(max_digits=19, decimal_places=8)),
            ),
            "tip_earnings": Coalesce(
                Subquery(
                    Distribution.objects.filter(**tips_conditions)
                    .values("recipient_id")
                    .annotate(total=Sum("amount"))
                    .values("total"),
                    output_field=DecimalField(max_digits=19, decimal_places=8),
                ),
                Value(0, output_field=DecimalField(max_digits=19, decimal_places=8)),
            ),
            "earned_rsc": F("bounty_earnings") + F("tip_earnings"),
        }

    def _create_sum_annotation(
        self,
        model,
        conditions,
        id_field="user_id",
        amount_field="amount",
        needs_cast=False,
    ):
        """
        Generic helper method to create a sum annotation with optional casting

        Args:
            model: The model to query
            conditions: Filter conditions
            id_field: Field to group by (default: user_id)
            amount_field: Field to sum (default: amount)
            needs_cast: Whether to cast the amount field to Decimal (default: False)
        """
        query = model.objects.filter(**conditions)

        if needs_cast:
            query = query.annotate(
                numeric_amount=Cast(
                    amount_field,
                    output_field=DecimalField(max_digits=19, decimal_places=8),
                )
            )
            amount_field = "numeric_amount"

        return Coalesce(
            Subquery(
                query.values(id_field)
                .annotate(total=Sum(amount_field))
                .values("total"),
                output_field=DecimalField(max_digits=19, decimal_places=8),
            ),
            Value(0, output_field=DecimalField(max_digits=19, decimal_places=8)),
        )

    def _create_funder_earnings_annotation(self, start_date=None, end_date=None):
        """Creates annotation dictionary for funder earnings calculations"""
        purchase_conditions = self._get_funder_purchase_conditions(start_date, end_date)
        bounty_conditions = self._get_funder_bounty_conditions(start_date, end_date)
        distribution_conditions = self._get_funder_distribution_conditions(
            start_date, end_date
        )

        return {
            "purchase_funding": self._create_sum_annotation(
                Purchase,
                purchase_conditions,
                needs_cast=True,  # Purchase amount needs casting since it's text
            ),
            "bounty_funding": self._create_sum_annotation(
                Bounty, bounty_conditions, id_field="created_by_id"
            ),
            "distribution_funding": self._create_sum_annotation(
                Distribution, distribution_conditions, id_field="giver_id"
            ),
            "total_funding": F("purchase_funding")
            + F("bounty_funding")
            + F("distribution_funding"),
        }

    def _validate_date_range(self, start_date, end_date, max_days=30):
        """
        Validates that the date range doesn't exceed the maximum allowed days.

        Args:
            start_date: Start date string in ISO format
            end_date: End date string in ISO format
            max_days: Maximum allowed days between dates (default: 30)

        Returns:
            tuple: (is_valid, error_response)
                - is_valid: Boolean indicating if the range is valid
                - error_response: Response object with error details if invalid, None otherwise
        """
        if not (start_date and end_date):
            return True, None

        try:
            # Parse date strings directly to date objects (not datetime)
            # This avoids timezone issues and focuses just on the date part
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()

            # Calculate days between dates
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

        # Get breakdowns
        reviewer_user_ids = [entry.user_id for entry in reviewer_entries]
        funder_user_ids = [entry.user_id for entry in funder_entries]

        reviewer_start_date, reviewer_end_date = self._get_period_date_range(
            Leaderboard.SEVEN_DAYS
        )
        funder_start_date, funder_end_date = self._get_period_date_range(
            Leaderboard.THIRTY_DAYS
        )

        reviewer_breakdowns = self._get_reviewer_breakdowns_from_funding_activity(
            reviewer_user_ids, reviewer_start_date, reviewer_end_date
        )
        funder_breakdowns = self._get_funder_breakdowns_from_funding_activity(
            funder_user_ids, funder_start_date, funder_end_date
        )

        return Response(
            {
                "reviewers": [
                    {
                        **self.serialize_user(entry.user),
                        "earned_rsc": entry.total_amount,
                        "bounty_earnings": reviewer_breakdowns.get(
                            entry.user_id, {}
                        ).get("bounty_earnings", 0),
                        "tip_earnings": reviewer_breakdowns.get(entry.user_id, {}).get(
                            "tip_earnings", 0
                        ),
                    }
                    for entry in reviewer_entries
                ],
                "funders": [
                    {
                        **self.serialize_user(entry.user),
                        "total_funding": entry.total_amount,
                        "purchase_funding": funder_breakdowns.get(
                            entry.user_id, {}
                        ).get("purchase_funding", 0),
                        "bounty_funding": funder_breakdowns.get(entry.user_id, {}).get(
                            "bounty_funding", 0
                        ),
                        "distribution_funding": funder_breakdowns.get(
                            entry.user_id, {}
                        ).get("distribution_funding", 0),
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
                # Use pre-computed leaderboard
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

                # Get breakdowns for the users in this page
                user_ids = [entry.user_id for entry in page]
                start_date_dt, end_date_dt = self._get_period_date_range(
                    leaderboard_period
                )
                breakdowns = self._get_reviewer_breakdowns_from_funding_activity(
                    user_ids, start_date_dt, end_date_dt
                )

                data = []
                for entry in page:
                    user_data = self.serialize_user(entry.user)
                    breakdown = breakdowns.get(entry.user_id, {})
                    data.append(
                        {
                            **user_data,
                            "earned_rsc": entry.total_amount,
                            "bounty_earnings": breakdown.get("bounty_earnings", 0),
                            "tip_earnings": breakdown.get("tip_earnings", 0),
                        }
                    )
                return self.get_paginated_response(data)

        # Fallback to on-the-fly calculation for custom date ranges
        # Validate date range doesn't exceed 30 days
        is_valid, error_response = self._validate_date_range(start_date, end_date, 30)
        if not is_valid:
            return error_response

        reviewers = (
            self.get_queryset()
            .annotate(**self._create_reviewer_earnings_annotation(start_date, end_date))
            .order_by("-earned_rsc")
        )

        page = self.paginate_queryset(reviewers)
        data = [
            {
                **self.serialize_user(reviewer),
                "earned_rsc": reviewer.earned_rsc,
                "bounty_earnings": reviewer.bounty_earnings,
                "tip_earnings": reviewer.tip_earnings,
            }
            for reviewer in page
        ]
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
                # Use pre-computed leaderboard
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

                # Get breakdowns for the users in this page
                user_ids = [entry.user_id for entry in page]
                start_date_dt, end_date_dt = self._get_period_date_range(
                    leaderboard_period
                )
                breakdowns = self._get_funder_breakdowns_from_funding_activity(
                    user_ids, start_date_dt, end_date_dt
                )

                data = []
                for entry in page:
                    user_data = self.serialize_user(entry.user)
                    breakdown = breakdowns.get(entry.user_id, {})
                    data.append(
                        {
                            **user_data,
                            "total_funding": entry.total_amount,
                            "purchase_funding": breakdown.get("purchase_funding", 0),
                            "bounty_funding": breakdown.get("bounty_funding", 0),
                            "distribution_funding": breakdown.get(
                                "distribution_funding", 0
                            ),
                        }
                    )
                return self.get_paginated_response(data)

        # Fallback to on-the-fly calculation for custom date ranges
        # Validate date range doesn't exceed 30 days
        is_valid, error_response = self._validate_date_range(start_date, end_date, 30)
        if not is_valid:
            return error_response

        top_funders = (
            self.get_queryset()
            .annotate(**self._create_funder_earnings_annotation(start_date, end_date))
            .order_by("-total_funding")
        )

        page = self.paginate_queryset(top_funders)
        data = [
            {
                **self.serialize_user(funder),
                "total_funding": funder.total_funding,
                "purchase_funding": funder.purchase_funding,
                "bounty_funding": funder.bounty_funding,
                "distribution_funding": funder.distribution_funding,
            }
            for funder in page
        ]
        return self.get_paginated_response(data)
