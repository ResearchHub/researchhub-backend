"""
Specialized feed view focused on funding-related content for ResearchHub.
This view uses the Feed serializer on preregistration posts, instantiating
feed entries for each post instead of querying the feed table.
This is done for three reasons:
1. To provide a consistent endpoint for feed content.
2. Avoid filtering on feed entries which can be expensive since it is a large table.
3. Older feed entries are not in the feed table.
"""

from django.core.cache import cache
from django.db.models import (
    BooleanField,
    Case,
    DecimalField,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from feed.models import FeedEntry
from feed.serializers import FundingFeedEntrySerializer
from feed.views.feed_ordering_mixin import FeedOrderingMixin
from feed.views.feed_view_mixin import FeedViewMixin
from purchase.related_models.fundraise_model import Fundraise
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

from ..serializers import PostSerializer, serialize_feed_metrics
from .common import FeedPagination


class FundingFeedViewSet(FeedOrderingMixin, FeedViewMixin, ModelViewSet):
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
    - ordering: Sort order
      Options:
        - newest (default): Sort by creation date (newest first)
        - hot_score: Sort by trending score (most engaging content)
        - upvotes: Sort by score (most upvoted first)
        - amount_raised: Sort by amount raised (highest first)
    """

    serializer_class = PostSerializer
    permission_classes = []
    pagination_class = FeedPagination

    def _get_open_status(self):
        return Fundraise.OPEN

    def get_cache_key(self, request, feed_type=""):
        """Override to include funding-specific cache version"""
        base_key = super().get_cache_key(request, feed_type)
        return base_key + "-v2"

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    def list(self, request, *args, **kwargs):
        page = request.query_params.get("page", "1")
        page_num = int(page)
        grant_id = request.query_params.get("grant_id", None)
        created_by = request.query_params.get("created_by", None)
        fundraise_status = request.query_params.get("fundraise_status", None)
        ordering = request.query_params.get("ordering", None)
        cache_key = self.get_cache_key(request, "funding")
        use_cache = page_num < 4 and grant_id is None and created_by is None and fundraise_status is None and ordering is None

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
        Additionally filter by fundraise status, grant applications, and/or created_by if specified.
        """
        fundraise_status = self.request.query_params.get("fundraise_status", None)
        grant_id = self.request.query_params.get("grant_id", None)
        created_by = self.request.query_params.get("created_by", None)

        now = timezone.now()
        fundraise_status_subquery = Fundraise.objects.filter(
            unified_document_id=OuterRef("unified_document_id")
        ).annotate(
            priority=Case(
                When(
                    Q(status=Fundraise.OPEN) & (Q(end_date__isnull=True) | Q(end_date__gt=now)),
                    then=Value(0)
                ),
                default=Value(1),
                output_field=IntegerField()
            )
        ).values("priority").order_by("priority")[:1]

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
            .annotate(
                status_priority=Subquery(fundraise_status_subquery, output_field=IntegerField())
            )
        )

        # Filter by created_by if provided
        if created_by:
            queryset = queryset.filter(created_by__id=created_by)

        # Common field paths for ordering
        status_field = "status_priority"
        end_date_field = "unified_document__fundraises__end_date"
        ordering = self.request.query_params.get("ordering")
        
        # Filter by grant applications if grant_id is provided
        if grant_id:
            queryset = queryset.filter(grant_applications__grant_id=grant_id)
            return self.apply_ordering(queryset, ordering, status_field, end_date_field)

        # Apply filters and ordering based on fundraise_status
        if fundraise_status:
            if fundraise_status.upper() == "OPEN":
                queryset = queryset.filter(
                    unified_document__fundraises__status__in=[Fundraise.OPEN, Fundraise.COMPLETED]
                )
                queryset = self.apply_ordering(queryset, ordering, status_field, end_date_field)
            elif fundraise_status.upper() == "CLOSED":
                queryset = queryset.filter(
                    unified_document__fundraises__status=Fundraise.COMPLETED
                )
                # CLOSED defaults to end_date sorting when no ordering specified
                queryset = self.apply_ordering(
                    queryset, 
                    ordering, 
                    status_field, 
                    end_date_field
                ) if ordering else queryset.order_by(f"-{end_date_field}")
        else:
            queryset = self.apply_ordering(queryset, ordering, status_field, end_date_field)

        return queryset
