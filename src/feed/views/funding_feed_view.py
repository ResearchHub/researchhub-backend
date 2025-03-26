"""
Specialized feed view focused on funding-related content for ResearchHub.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from requests import Request
from rest_framework import viewsets
from rest_framework.response import Response

from discussion.reaction_serializers import VoteSerializer as GrmVoteSerializer
from feed.models import FeedEntry
from feed.serializers import FeedEntrySerializer
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.views.researchhub_unified_document_views import get_user_votes

from ..serializers import PostSerializer
from .common import DEFAULT_CACHE_TIMEOUT, FeedPagination


class FundingFeedViewSet(viewsets.ModelViewSet):
    """
    ViewSet for accessing entries specifically related to preregistration documents.
    This provides a dedicated endpoint for clients to fetch and display preregistration
    content in the Research Hub platform.
    """

    serializer_class = PostSerializer
    permission_classes = []
    pagination_class = FeedPagination

    def list(self, request, *args, **kwargs):
        page = request.query_params.get("page", "1")
        page_num = int(page)
        cache_key = self._get_cache_key(request)
        use_cache = page_num < 4

        if use_cache:
            # try to get cached response
            cached_response = cache.get(cache_key)
            if cached_response:
                if request.user.is_authenticated:
                    self._add_user_votes_to_response(request.user, cached_response)
                return Response(cached_response)

        # Get paginated posts
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)

        # Create content type for posts
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

        # Create fake feed entries
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

        # Serialize using FeedEntrySerializer
        serializer = FeedEntrySerializer(feed_entries, many=True)
        response_data = self.get_paginated_response(serializer.data).data

        # Add user votes if authenticated
        if request.user.is_authenticated:
            self._add_user_votes_to_response(request.user, response_data)

        # Cache if needed
        if use_cache:
            cache.set(cache_key, response_data, timeout=DEFAULT_CACHE_TIMEOUT)

        return Response(response_data)

    def _add_user_votes_to_response(self, user, response_data):
        """
        Add user votes to preregistration items in the response data.
        """
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

        post_ids = []
        for item in response_data["results"]:
            if item.get("content_type") == "RESEARCHHUBPOST":
                post_ids.append(int(item["content_object"]["id"]))

        if not post_ids:
            return

        post_votes = get_user_votes(
            user,
            post_ids,
            post_content_type,
        )

        post_votes_map = {}
        for vote in post_votes:
            post_votes_map[int(vote.object_id)] = GrmVoteSerializer(vote).data

        for item in response_data["results"]:
            if item.get("content_type") == "RESEARCHHUBPOST":
                post_id = int(item["content_object"]["id"])
                if post_id in post_votes_map:
                    item["user_vote"] = post_votes_map[post_id]

    def _get_cache_key(self, request: Request) -> str:
        """
        Generate a cache key for the preregistration feed response.
        """
        user_id = request.user.id if request.user.is_authenticated else None

        page = request.query_params.get("page", "1")
        page_size = request.query_params.get(
            self.pagination_class.page_size_query_param,
            str(self.pagination_class.page_size),
        )

        user_part = f"{user_id or 'anonymous'}"
        pagination_part = f"{page}-{page_size}"

        return f"funding_feed:{user_part}:{pagination_part}"

    def get_queryset(self):
        """
        Filter to only include posts that are preregistrations.
        """

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

        queryset = queryset.order_by("-created_date")

        return queryset
