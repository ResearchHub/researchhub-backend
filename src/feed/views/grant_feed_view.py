"""
Specialized feed view focused on grant-related content for ResearchHub.
This view displays grants in a feed format, showing funding opportunities
and research grant postings.
"""

from django.core.cache import cache
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from feed.models import FeedEntry
from feed.serializers import GrantFeedEntrySerializer
from feed.views.feed_view_mixin import FeedViewMixin
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
    """

    serializer_class = PostSerializer
    permission_classes = []
    pagination_class = FeedPagination
    
    # Funding status filtering configuration
    model_class = Grant
    status_field = "unified_document__grants__status"
    end_date_field = "unified_document__grants__end_date"

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

        grant_params = f"-status:{status}-org:{organization}"
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
        Additionally filter by grant status or organization if specified.
        """
        status = self.request.query_params.get("status", None)
        organization = self.request.query_params.get("organization", None)

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

        # Apply funding status-based filtering using the mixin
        queryset = self.apply_funding_status_filtering(queryset, status)

        return queryset
