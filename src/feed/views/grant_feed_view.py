"""
Specialized feed view focused on grant-related content for ResearchHub.
This view displays grants in a feed format, showing funding opportunities
and research grant postings.
"""

import json

from django.core.cache import cache
from django.db.models import BooleanField, Case, F, Value, When
from django.db.models.expressions import OrderBy
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from feed.models import FeedEntry
from feed.serializers import GrantFeedEntrySerializer
from feed.views.feed_view_mixin import FeedViewMixin
from hub.models import Hub
from purchase.related_models.grant_model import Grant
from researchhub_document.related_models.constants.document_type import GRANT
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

from ..serializers import PostSerializer, serialize_feed_metrics
from .common import FeedPagination


class GrantFeedViewSet(FeedViewMixin, ModelViewSet):
    """
    ViewSet for accessing entries specifically related to grant documents.
    This provides a dedicated endpoint for clients to fetch and display grant
    content in the Research Hub platform.

    Query Parameters:
    - status: Filter by grant status
      Options:
        - OPEN: Only show posts with open grants
        - CLOSED: Only show posts with closed grants
        - COMPLETED: Only show posts with completed grants
    - organization: Filter by granting organization name (partial match)
    - hub: Filter by associated hubs
    - ordering: Set order of response.
      Options:
        - created_date: Sort by creation date (newest first)
        - unified_document__grants__amount: Sort by grant amount (highest first)
        - unified_document__grants__end_date: Sort by grant end date (soonest first)
    """

    serializer_class = PostSerializer
    permission_classes = []
    pagination_class = FeedPagination

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    def get_cache_key(self, request, feed_type=""):
        """Override to include grant-specific query parameters in cache key"""
        base_key = super().get_cache_key(request, feed_type)

        # Add grant-specific parameters to cache key
        status = request.query_params.get("status", "")
        organization = request.query_params.get("organization", "")
        order = request.query_params.get("ordering", "")
        hub = request.query_params.get("hub_ids", "")

        grant_params = f"-status:{status}-org:{organization}-order:{order}-hubs:{hub}"
        return base_key + grant_params

    def list(self, request, *args, **kwargs):
        page = request.query_params.get("page", "1")
        page_num = int(page)
        cache_key = self.get_cache_key(request, "grants")
        use_cache = page_num < 4

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

        serializer = GrantFeedEntrySerializer(feed_entries, many=True)
        response_data = self.get_paginated_response(serializer.data).data

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response_data)

        if use_cache:
            cache.set(cache_key, response_data, timeout=self.DEFAULT_CACHE_TIMEOUT)

        return Response(response_data)

    def get_queryset(self):
        """
        Filter to only include posts that are grants.
        Additionally filter by grant status, organization, or hub.
        """

        status = self.request.query_params.get("fundraise_status", None)
        organization = self.request.query_params.get("organization", None)
        hubs = self.request.query_params.get("hub_ids", None)

        # get all grants.
        queryset = (
            ResearchhubPost.objects.all()
            .select_related(
                "created_by",
                "created_by__author_profile",
                "unified_document",
            )
            .prefetch_related(
                "unified_document__hubs",
                "unified_document__grants",
                "unified_document__grants__applications__applicant__author_profile",
            )
            .filter(document_type=GRANT)
            .filter(unified_document__is_removed=False)
        )

        # Filter by organization if specified
        if organization:
            queryset = queryset.filter(
                unified_document__grants__organization__icontains=organization
            )

        # Filter by Hub if specified.
        if hubs:
            try:
                hub_json = json.loads(hubs)
                queryset = queryset.filter(unified_document__hubs__id__in=hub_json)
            except json.JSONDecodeError as e:
                print("Invalid JSON for hub_ids: ", e)
                pass

        # Filter by Status if specified.
        if status:
            queryset = queryset.filter(unified_document__grants__status=status)

        return queryset

    def ordering(self, queryset):
        """
        Order by user specified order param, default open to top.
        """

        ordering = self.request.query_params.get("ordering", "-created_date")
        status = self.request.query_params.get("fundraise_status", None)

        ordering_options = [
            "-created_date",
            "-unified_document__grants__amount",
            "unified_document__grants__end_date",
        ]

        if ordering not in ordering_options:
            ordering = "-created_date"

        queryset = queryset.annotate(
            is_open=Case(
                When(
                    unified_document__grants__status=Grant.OPEN,
                    unified_document__grants__end_date__gte=timezone.now(),
                    then=Value(True),
                ),
                default=Value(False),
                output_field=BooleanField(),
            ),
        ).order_by(
            OrderBy(
                F("is_open"),
                descending=bool(not status or status.upper() == Grant.OPEN),
            ),
            ordering,
        )

        return queryset

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def hubs(self, request):
        """
        Get list of hubs that have grant posts.
        """

        cache_key = "funding-hubs"
        cache_hit = cache.get(cache_key)
        if cache_hit:
            return Response(cache_hit, status=200)

        hub_data = list(
            Hub.objects.filter(
                related_documents__document_type=GRANT,
                is_removed=False,
            )
            .values("id", "name", "slug")
            .distinct()
        )

        cache.set(cache_key, hub_data, timeout=60 * 60)

        return Response(hub_data, status=200)
