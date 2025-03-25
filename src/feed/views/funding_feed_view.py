"""
Specialized feed view focused on funding-related content for ResearchHub.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from requests import Request
from rest_framework import viewsets
from rest_framework.response import Response

from discussion.reaction_serializers import VoteSerializer as GrmVoteSerializer
from hub.models import Hub
from paper.related_models.paper_model import Paper
from reputation.related_models.bounty import Bounty
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.views.researchhub_unified_document_views import get_user_votes

from ..models import FeedEntry
from ..serializers import FeedEntrySerializer
from .common import DEFAULT_CACHE_TIMEOUT, FeedPagination


class FundingFeedViewSet(viewsets.ModelViewSet):
    """
    ViewSet for accessing feed entries specifically related to fundraising activities.
    This provides a dedicated endpoint for clients to fetch and display funding-related
    content in the Research Hub platform.
    """

    serializer_class = FeedEntrySerializer
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

        response = super().list(request, *args, **kwargs)

        if use_cache:
            # cache response
            cache.set(cache_key, response.data, timeout=DEFAULT_CACHE_TIMEOUT)

        if request.user.is_authenticated:
            self._add_user_votes_to_response(request.user, response.data)

        return response

    def _add_user_votes_to_response(self, user, response_data):
        """
        Add user votes to funding feed items in the response data.
        Reuses the implementation from FeedViewSet.
        """
        # Get content types once to avoid repeated database queries
        paper_content_type = ContentType.objects.get_for_model(Paper)
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        comment_content_type = ContentType.objects.get_for_model(RhCommentModel)
        bounty_content_type = ContentType.objects.get_for_model(Bounty)

        # Get uppercase model names from ContentType objects
        paper_type_str = paper_content_type.model.upper()
        post_type_str = post_content_type.model.upper()
        comment_type_str = comment_content_type.model.upper()
        bounty_type_str = bounty_content_type.model.upper()

        # Map content type strings to their ContentType objects
        content_type_map = {
            paper_type_str: paper_content_type,
            post_type_str: post_content_type,
            comment_type_str: comment_content_type,
            bounty_type_str: bounty_content_type,
        }

        paper_ids = []
        post_ids = []
        comment_ids = []

        # Collect IDs for each content type
        for item in response_data["results"]:
            content_type_str = item.get("content_type")
            if content_type_str == paper_type_str:
                paper_ids.append(int(item["content_object"]["id"]))
            elif content_type_str == post_type_str:
                post_ids.append(int(item["content_object"]["id"]))
            elif content_type_str == comment_type_str:
                comment_ids.append(int(item["content_object"]["id"]))
            elif content_type_str == bounty_type_str:
                # For bounties, we need to get the comment ID if it exists
                if item["content_object"].get("comment") and item["content_object"][
                    "comment"
                ].get("id"):
                    comment_ids.append(int(item["content_object"]["comment"]["id"]))

        # Process paper votes
        if paper_ids:
            paper_votes = get_user_votes(
                user,
                paper_ids,
                content_type_map[paper_type_str],
            )

            paper_votes_map = {}
            for vote in paper_votes:
                paper_votes_map[int(vote.object_id)] = GrmVoteSerializer(vote).data

            for item in response_data["results"]:
                if item.get("content_type") == paper_type_str:
                    paper_id = int(item["content_object"]["id"])
                    if paper_id in paper_votes_map:
                        item["user_vote"] = paper_votes_map[paper_id]

        # Process post votes
        if post_ids:
            post_votes = get_user_votes(
                user,
                post_ids,
                content_type_map[post_type_str],
            )

            post_votes_map = {}
            for vote in post_votes:
                post_votes_map[int(vote.object_id)] = GrmVoteSerializer(vote).data

            for item in response_data["results"]:
                if item.get("content_type") == post_type_str:
                    post_id = int(item["content_object"]["id"])
                    if post_id in post_votes_map:
                        item["user_vote"] = post_votes_map[post_id]

        # Process comment votes
        if comment_ids:
            comment_votes = get_user_votes(
                user,
                comment_ids,
                content_type_map[comment_type_str],
            )

            comment_votes_map = {}
            for vote in comment_votes:
                comment_votes_map[int(vote.object_id)] = GrmVoteSerializer(vote).data

            for item in response_data["results"]:
                if item.get("content_type") == comment_type_str:
                    comment_id = int(item["content_object"]["id"])
                    if comment_id in comment_votes_map:
                        item["user_vote"] = comment_votes_map[comment_id]
                # Handle bounties with comments
                elif item.get("content_type") == bounty_type_str and item[
                    "content_object"
                ].get("comment"):
                    comment_id = int(item["content_object"]["comment"]["id"])
                    if comment_id in comment_votes_map:
                        item["user_vote"] = comment_votes_map[comment_id]

    def _get_cache_key(self, request: Request) -> str:
        """
        Generate a cache key for the funding feed response.
        """
        hub_slug = request.query_params.get("hub_slug")
        user_id = request.user.id if request.user.is_authenticated else None

        page = request.query_params.get("page", "1")
        page_size = request.query_params.get(
            self.pagination_class.page_size_query_param,
            str(self.pagination_class.page_size),
        )

        hub_part = hub_slug or "all"
        user_part = f"{user_id or 'anonymous'}"
        pagination_part = f"{page}-{page_size}"

        return f"funding_feed:{hub_part}:{user_part}:{pagination_part}"

    def get_queryset(self):
        """
        Filter feed entries to only include those related to fundraising activities.
        This includes entries with unified documents that have associated fundraises.
        """
        hub_slug = self.request.query_params.get("hub_slug")

        queryset = (
            FeedEntry.objects.all()
            .select_related(
                "content_type",
                "parent_content_type",
                "user",
                "user__author_profile",
            )
            .prefetch_related(
                "unified_document",
                "unified_document__hubs",
                "unified_document__fundraises",
            )
            # Filter for entries related to documents that have fundraises
            .filter(unified_document__fundraises__isnull=False)
        )

        # Apply hub filter if hub_slug is provided
        if hub_slug:
            try:
                hub = Hub.objects.get(slug=hub_slug)
                queryset = queryset.filter(unified_document__hubs=hub)
            except Hub.DoesNotExist:
                return FeedEntry.objects.none()

        # Get the most recent entry per content object
        sub_qs = queryset.order_by(
            "content_type_id", "object_id", "-action_date"
        ).distinct("content_type_id", "object_id")

        # Final queryset ordered by action date
        final_qs = queryset.filter(pk__in=sub_qs.values("pk")).order_by("-action_date")

        return final_qs
