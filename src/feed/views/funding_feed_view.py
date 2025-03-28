"""
Specialized feed view focused on funding-related content for ResearchHub.
This view uses the Feed serializer on preregistration posts, instantiating
feed entries for each post instead of querying the feed table.
This is done for three reasons:
1. To provide a consistent endpoint for feed content.
2. Avoid filtering on feed entries which can be expensive since it is a large table.
3. Older feed entries are not in the feed table.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db.models import Q
from rest_framework import viewsets
from rest_framework.response import Response

from feed.models import FeedEntry
from feed.serializers import FeedEntrySerializer
from purchase.related_models.fundraise_model import Fundraise
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

from ..serializers import PostSerializer
from .common import (
    DEFAULT_CACHE_TIMEOUT,
    FeedPagination,
    add_user_votes_to_response,
    get_cache_key,
    get_common_serializer_context,
)


class FundingFeedViewSet(viewsets.ModelViewSet):
    """
    ViewSet for accessing entries specifically related to preregistration documents.
    This provides a dedicated endpoint for clients to fetch and display preregistration
    content in the Research Hub platform.

    Query Parameters:
    - fundraise_status: Filter by fundraise status
      Options:
        - OPEN: Only show posts with open fundraises
        - CLOSED: Only show posts with closed or completed fundraises
    """

    serializer_class = PostSerializer
    permission_classes = []
    pagination_class = FeedPagination

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(get_common_serializer_context())
        return context

    def list(self, request, *args, **kwargs):
        page = request.query_params.get("page", "1")
        page_num = int(page)
        cache_key = get_cache_key(request, "funding")
        use_cache = page_num < 4

        if use_cache:
            # try to get cached response
            cached_response = cache.get(cache_key)
            if cached_response:
                if request.user.is_authenticated:
                    add_user_votes_to_response(request.user, cached_response)
                return Response(cached_response)

        # Get paginated posts
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)

        # Create content type for posts
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

        feed_entries = []
        for post in page:
            # Create an unsaved FeedEntry instance
            feed_entry = FeedEntry(
                id=post.id,  # We can use the post ID as a temporary ID
                content_type=post_content_type,
                object_id=post.id,
                action="PUBLISH",
                action_date=post.created_date,
                user=post.created_by,
                unified_document=post.unified_document,
            )
            feed_entry.item = post
            feed_entries.append(feed_entry)

        serializer = FeedEntrySerializer(feed_entries, many=True)
        response_data = self.get_paginated_response(serializer.data).data

        if request.user.is_authenticated:
            add_user_votes_to_response(request.user, response_data)

        if use_cache:
            cache.set(cache_key, response_data, timeout=DEFAULT_CACHE_TIMEOUT)

        return Response(response_data)

    def get_queryset(self):
        """
        Filter to only include posts that are preregistrations.
        Additionally filter by fundraise status if specified.
        """
        fundraise_status = self.request.query_params.get("fundraise_status", None)

        queryset = (
            ResearchhubPost.objects.all()
            .select_related(
                "created_by",
                "created_by__author_profile",
                "unified_document",
            )
            .prefetch_related(
                "unified_document__hubs",
            )
            .filter(document_type=PREREGISTRATION)
            .filter(unified_document__is_removed=False)
        )

        if fundraise_status:
            if fundraise_status.upper() == "OPEN":
                queryset = queryset.filter(
                    unified_document__fundraises__status=Fundraise.OPEN
                )
            elif fundraise_status.upper() == "CLOSED":
                queryset = queryset.filter(
                    Q(unified_document__fundraises__status=Fundraise.CLOSED)
                    | Q(unified_document__fundraises__status=Fundraise.COMPLETED)
                )

        queryset = queryset.order_by("-created_date")

        return queryset
