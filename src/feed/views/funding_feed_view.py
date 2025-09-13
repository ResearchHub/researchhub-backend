"""
Specialized feed view focused on funding-related content for ResearchHub.
This view uses the Feed serializer on preregistration posts, instantiating
feed entries for each post instead of querying the feed table.
This is done for three reasons:
1. To provide a consistent endpoint for feed content.
2. Avoid filtering on feed entries which can be expensive since it is a large table.
3. Older feed entries are not in the feed table.
"""

from urllib.parse import parse_qs, unquote_plus

from django.core.cache import cache
from django.db.models import (
    Avg,
    BooleanField,
    Case,
    Count,
    DecimalField,
    F,
    FloatField,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from feed.models import FeedEntry
from feed.serializers import FundingFeedEntrySerializer
from feed.views.feed_view_mixin import FeedViewMixin
from purchase.related_models.fundraise_model import Fundraise
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.related_models.user_verification_model import UserVerification

from ..serializers import PostSerializer, serialize_feed_metrics
from .common import FeedPagination


class FundingFeedViewSet(FeedViewMixin, ModelViewSet):
    """
    ViewSet for accessing entries specifically related to preregistration documents.
    This provides a dedicated endpoint for clients to fetch and display preregistration
    content in the Research Hub platform.

    Query Parameters:
    - fundraise_status: Filter by fundraise status
      Options:
        * OPEN: Only show posts with open fundraises
        * CLOSED: Only show posts with completed fundraises

    - grant_id: Filter by grant applications
      (show only posts that applied to specific grant)
    - created_by: Filter by user ID who created the funding post
    - ordering: Sort order when grant_id is provided
      Options:
        * newest (default): Sort by creation date (newest first)
        * hot_score: Sort by hot score (most popular first)
        * upvotes: Sort by score (most upvoted first)
        * amount_raised: Sort by amount raised (highest first)

    - filtering: More granular control, represented as URL encoded parameters
      Options:
        * hub_ids: Comma-separated list of hub IDs to filter posts by associated topics
        * min_upvotes: Minimum number of upvotes to be included
        * min_score: Minimum score to be included
        * verified_authors_only: If set to true, only include verified authors
        * tax_deductible: If set to true, only include posts with tax-deductible fundraises
    """

    serializer_class = PostSerializer
    permission_classes = []
    pagination_class = FeedPagination

    def _order_by_amount_raised(self, queryset):
        return queryset.annotate(
            amount_raised=Coalesce(
                Sum("unified_document__fundraises__escrow__amount_holding")
                + Sum("unified_document__fundraises__escrow__amount_paid"),
                0,
                output_field=DecimalField(),
            )
        ).order_by("-amount_raised")

    def _order_by_goal_percent(self, queryset):
        # TODO: jmargulis: Consider addressing the difference between RSC and USD in
        # escrow and goal_amount. It is possible that the rate between RSC and USD
        # changes drastically during the fundraise period
        return queryset.annotate(
            goal_percent=Case(
                When(
                    unified_document__fundraises__goal_amount=0,
                    then=Value(0.0),
                ),
                default=Coalesce(
                    Sum("unified_document__fundraises__escrow__amount_holding")
                    + Sum("unified_document__fundraises__escrow__amount_paid"),
                    0,
                )
                / F("unified_document__fundraises__goal_amount"),
                output_field=FloatField(),
            )
        ).order_by("-goal_percent")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    def list(self, request, *args, **kwargs):
        page = request.query_params.get("page", "1")
        page_num = int(page)
        grant_id = request.query_params.get("grant_id", None)
        created_by = request.query_params.get("created_by", None)
        cache_key = self.get_cache_key(request, "funding")
        use_cache = page_num < 4 and grant_id is None and created_by is None

        if use_cache:
            # try to get cached response
            cached_response = cache.get(cache_key)
            if cached_response:
                if request.user.is_authenticated:
                    self.add_user_votes_to_response(request.user, cached_response)
                return Response(cached_response)

        # Get paginated posts
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)

        feed_entries = []
        for post in page:
            # Create an unsaved FeedEntry instance
            feed_entry = FeedEntry(
                id=post.id,  # We can use the post ID as a temporary ID
                content_type=self._post_content_type,
                object_id=post.id,
                action="PUBLISH",
                action_date=post.created_date,
                user=post.created_by,
                unified_document=post.unified_document,
            )
            feed_entry.item = post
            metrics = serialize_feed_metrics(post, self._post_content_type)
            feed_entry.metrics = metrics
            feed_entries.append(feed_entry)

        serializer = FundingFeedEntrySerializer(feed_entries, many=True)
        response_data = self.get_paginated_response(serializer.data).data

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response_data)

        if use_cache:
            cache.set(cache_key, response_data, timeout=self.DEFAULT_CACHE_TIMEOUT)

        return Response(response_data)

    def get_queryset(self):
        """
        Filter to only include posts that are preregistrations.
        Additionally filter by fundraise status, grant applications,
        and/or created_by if specified, and filtering parameters.
        """
        fundraise_status = self.request.query_params.get("fundraise_status", None)
        grant_id = self.request.query_params.get("grant_id", None)
        created_by = self.request.query_params.get("created_by", None)
        filtering = self.request.query_params.get("filtering", None)

        queryset = (
            ResearchhubPost.objects.all()
            .select_related(
                "created_by",
                "created_by__author_profile",
                "created_by__userverification",
                "unified_document",
            )
            .prefetch_related(
                "unified_document__hubs",
                "unified_document__fundraises",
            )
            .filter(document_type=PREREGISTRATION)
            .filter(unified_document__is_removed=False)
        )

        # Filter by created_by if provided
        if created_by:
            queryset = queryset.filter(created_by__id=created_by)

        # Filter by grant applications if grant_id is provided
        if grant_id:
            queryset = queryset.filter(grant_applications__grant_id=grant_id)

            # Add custom sorting for grant applications
            ordering = self.request.query_params.get("ordering", "-created_date")
            if ordering == "hot_score":
                queryset = queryset.order_by("-unified_document__hot_score")
            elif ordering == "upvotes":
                queryset = queryset.order_by("-score")
            elif ordering == "amount_raised":
                queryset = self._order_by_amount_raised(queryset)
            else:  # newest (default)
                queryset = queryset.order_by("-created_date")

            return queryset

        if fundraise_status:
            if fundraise_status.upper() == "OPEN":
                queryset = queryset.filter(
                    unified_document__fundraises__status=Fundraise.OPEN
                )
                # Order by end_date ascending (closest deadline first)
                queryset = queryset.order_by("unified_document__fundraises__end_date")
            elif fundraise_status.upper() == "CLOSED":
                queryset = queryset.filter(
                    unified_document__fundraises__status=Fundraise.COMPLETED
                )
                # Order by end date descending (most recent deadlines first)
                queryset = queryset.order_by("-unified_document__fundraises__end_date")
        else:
            # For ALL tab: We need different sorting for OPEN vs CLOSED/COMPLETED
            # Sort first by status (OPEN first), then apply different date sorts
            # based on status
            queryset = queryset.annotate(
                # Create a flag to identify OPEN fundraises
                is_open=Case(
                    When(
                        unified_document__fundraises__status=Fundraise.OPEN,
                        then=Value(True),
                    ),
                    default=Value(False),
                    output_field=BooleanField(),
                ),
            ).order_by(
                "-is_open",
                # For OPEN (is_open=True): Sort by closest (earliest) end_date first
                Case(
                    When(
                        is_open=True, then=F("unified_document__fundraises__end_date")
                    ),
                ),
                # For CLOSED (is_open=False): Sort by most recent end_date first
                Case(
                    When(
                        is_open=False, then=F("unified_document__fundraises__end_date")
                    ),
                    default=None,
                ).desc(),
            )

        if filtering:
            unquoted = unquote_plus(filtering)
            if not unquoted:
                pass

            params = parse_qs(unquoted)
            hub_ids = params.get("hub_ids", None)
            min_upvotes = params.get("min_upvotes", None)
            min_score = params.get("min_score", None)
            verified_authors_only = params.get("verified_authors_only", None)
            tax_deductible = params.get("tax_deductible", None)

            if hub_ids:
                try:
                    hub_ids = [int(hub_id) for hub_id in hub_ids[0].split(",")]
                    queryset = queryset.filter(unified_document__hubs__id__in=hub_ids)
                except ValueError:
                    pass
            if min_upvotes:
                try:
                    min_upvotes = int(min_upvotes[0])
                    if min_upvotes > 0:
                        queryset = queryset.annotate(num_votes=Count("votes")).filter(
                            num_votes__gte=min_upvotes
                        )
                except ValueError:
                    pass
            if min_score:
                try:
                    min_score = int(min_score[0])
                    if min_score > 0:
                        queryset = queryset.annotate(
                            avg_review_score=Avg("unified_document__reviews__score")
                        ).filter(avg_review_score__gte=min_score)
                except ValueError:
                    pass
            if verified_authors_only and verified_authors_only[0].lower() == "true":
                queryset = queryset.filter(
                    created_by__userverification__status=(
                        UserVerification.Status.APPROVED
                    ),
                )
            if tax_deductible and tax_deductible[0].lower() == "true":
                queryset = queryset.filter(
                    unified_document__fundraises__is_nonprofit=True
                )

        ordering = self.request.query_params.get("ordering")
        if ordering == "amount_raised":
            queryset = self._order_by_amount_raised(queryset)
        elif ordering == "newest":
            queryset = queryset.order_by("-created_date")
        elif ordering == "expiring":
            queryset = queryset.order_by("unified_document__fundraises__end_date")
        elif ordering == "upvotes":
            queryset = queryset.order_by("-score")
        elif ordering == "goal_percent":
            queryset = self._order_by_goal_percent(queryset)

        # print("==>", queryset.query)
        return queryset
