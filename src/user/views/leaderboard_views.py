from datetime import datetime, timedelta

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
        return self.queryset

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
        """Returns top 3 users for each category (reviewers and funders)"""
        start_date = timezone.now() - timedelta(days=7)

        top_reviewers = (
            self.get_queryset()
            .annotate(
                **self._create_reviewer_earnings_annotation(start_date=start_date)
            )
            .order_by("-earned_rsc")[:3]
        )

        top_funders = (
            self.get_queryset()
            .annotate(**self._create_funder_earnings_annotation(start_date=start_date))
            .order_by("-total_funding")[:3]
        )

        return Response(
            {
                "reviewers": [
                    {
                        **self.serialize_user(reviewer),
                        "earned_rsc": reviewer.earned_rsc,
                        "bounty_earnings": reviewer.bounty_earnings,
                        "tip_earnings": reviewer.tip_earnings,
                    }
                    for reviewer in top_reviewers
                ],
                "funders": [
                    {
                        **self.serialize_user(funder),
                        "total_funding": funder.total_funding,
                        "purchase_funding": funder.purchase_funding,
                        "bounty_funding": funder.bounty_funding,
                        "distribution_funding": funder.distribution_funding,
                    }
                    for funder in top_funders
                ],
            }
        )

    @method_decorator(cache_page(60 * 60 * 6))
    @action(detail=False, methods=[RequestMethods.GET])
    def reviewers(self, request):
        """Returns top reviewers for a given time period"""
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

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
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

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
