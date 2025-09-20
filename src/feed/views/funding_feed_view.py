"""
Specialized feed view focused on funding-related content for ResearchHub.
This view uses the Feed serializer on preregistration posts, instantiating
feed entries for each post instead of querying the feed table.
This is done for three reasons:
1. To provide a consistent endpoint for feed content.
2. Avoid filtering on feed entries which can be expensive since it is a large table.
3. Older feed entries are not in the feed table.
"""

import json

from django.core.cache import cache
from django.db.models import (
    BooleanField,
    Case,
    Count,
    DecimalField,
    DurationField,
    ExpressionWrapper,
    F,
    Sum,
    Value,
    When,
)
from django.db.models.expressions import OrderBy
from django.db.models.functions import Coalesce, Now
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from feed.models import FeedEntry
from feed.serializers import FundingFeedEntrySerializer
from feed.views.feed_view_mixin import FeedViewMixin
from purchase.related_models.fundraise_model import Fundraise
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

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
        - OPEN: Only show posts with open fundraises
        - CLOSED: Only show posts with completed fundraises
    - grant_id: Filter by grant applications
      (show only posts that applied to specific grant)
    - created_by: Filter by user ID who created the funding post
    - hub: Filter by associated hubs
    - ordering: Sort order when grant_id is provided
      Options:
        - newest (default): Sort by creation date (newest first)
        - hot_score: Sort by hot score (most popular first)
        - upvotes: Sort by score (most upvoted first)
        - amount_raised: Sort by amount raised (highest first)
        - created_date: Sort by creation date (newest first)
        - end_date: Sort by fundraise end date (closest to today)
    """

    serializer_class = PostSerializer
    permission_classes = []
    pagination_class = FeedPagination

    def get_cache_key(self, request, feed_type=""):
        """Override to include funding query parameters in cache key"""
        base_key = super().get_cache_key(request, feed_type)

        # Add funding-specific parameters to cache key
        order = request.query_params.get("ordering", "")
        hub = request.query_params.get("hub_ids", "")

        funding_params = f"-order:{order}-hubs:{hub}"
        return base_key + funding_params

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
        queryset = self.ordering(queryset)
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
        hub, and/or created_by if specified.
        """
        fundraise_status = self.request.query_params.get("fundraise_status", None)
        grant_id = self.request.query_params.get("grant_id", None)
        created_by = self.request.query_params.get("created_by", None)
        hubs = self.request.query_params.get("hub_ids", None)

        queryset = (
            ResearchhubPost.objects.all()
            .select_related(
                "created_by",
                "created_by__author_profile",
                "unified_document",
            )
            .prefetch_related(
                "unified_document__hubs",
                "unified_document__fundraises",
            )
            .filter(document_type=PREREGISTRATION)
            .filter(unified_document__is_removed=False)
        )

        # Filter by hubs if provided
        if hubs:
            try:
                hubs_json = json.loads(hubs)
                queryset = queryset.filter(
                    unified_document__hubs__id__in=hubs_json
                ).distinct()
            except Exception as e:
                print("Error serializing hubs: ", e)

        # Filter by created_by if provided
        if created_by:
            queryset = queryset.filter(created_by__id=created_by)

        # Filter by grant applications if grant_id is provided
        if grant_id:
            queryset = queryset.filter(grant_applications__grant_id=grant_id)

        # Filter status if specified
        if fundraise_status:
            if fundraise_status.upper() == Fundraise.OPEN:
                queryset = queryset.filter(
                    unified_document__fundraises__status=Fundraise.OPEN
                )
            else:
                queryset = queryset.filter(
                    unified_document__fundraises__status=Fundraise.COMPLETED
                )

        return queryset

    def ordering(self, queryset):
        """
        Order according to user preferences.
        """
        ordering_options_map = {
            "newest": "-created_date",
            "hot_score": "-unified_document__hot_score",
            "upvotes": "-score",
            "amount_raised": "-amount_raised",
            "end_date": "deadline_distance",
            "goal_amount": "-unified_document__fundraises__goal_amount",
            "review_count": "-review_count",
        }

        fundraise_status = self.request.query_params.get("fundraise_status", None)
        ordering = self.request.query_params.get("ordering", "end_date")

        # If ordering not a designated option, default to end_date
        if ordering not in ordering_options_map:
            ordering = "end_date"

        # Create flag for open status
        queryset = queryset.annotate(
            is_open=Case(
                When(
                    unified_document__fundraises__status=Fundraise.OPEN,
                    unified_document__fundraises__end_date__gte=Now(),
                    then=Value(True),
                ),
                default=Value(False),
                output_field=BooleanField(),
            ),
        )

        # Make reusable sort by status, move closed/completed items to bottom
        status_order = OrderBy(
            F("is_open"),
            descending=bool(
                not fundraise_status or fundraise_status.upper() == Fundraise.OPEN
            ),
        )

        if ordering == "end_date":
            queryset = queryset.annotate(
                deadline_delta=ExpressionWrapper(
                    F("unified_document__fundraises__end_date") - Now(),
                    output_field=DurationField(),
                ),
                deadline_distance=Case(
                    When(
                        is_open=True,
                        then=F("deadline_delta"),
                    ),
                    default=-F("deadline_delta"),
                    output_field=DurationField(),
                ),
            ).order_by(
                status_order,
                ordering_options_map[ordering],
            )
        elif ordering == "review_count":
            queryset = queryset.annotate(
                review_count=Count("unified_document__reviews", distinct=True)
            ).order_by(
                status_order,
                ordering_options_map[ordering],
            )
        elif ordering == "amount_raised":
            queryset = queryset.annotate(
                amount_raised=Coalesce(
                    Sum("unified_document__fundraises__escrow__amount_holding")
                    + Sum("unified_document__fundraises__escrow__amount_paid"),
                    0,
                    output_field=DecimalField(),
                )
            ).order_by(status_order, ordering_options_map[ordering])
        else:
            queryset = queryset.order_by(
                status_order,
                ordering_options_map[ordering],
            )

        return queryset

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def hubs(self, request):
        """
        Get list of hubs that have funding proposal posts.
        """

        CACHE_KEY = "funding-hubs"
        cache_hit = cache.get(CACHE_KEY)
        if cache_hit:
            return Response(cache_hit, status=200)

        hub_data = super().get_hubs(PREREGISTRATION)

        cache.set(CACHE_KEY, hub_data, timeout=super().DEFAULT_CACHE_TIMEOUT)

        return Response(hub_data, status=200)
