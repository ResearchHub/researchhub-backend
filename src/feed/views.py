from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import models
from django.db.models import Subquery
from requests import Request
from rest_framework import status, viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from discussion.reaction_serializers import VoteSerializer as GrmVoteSerializer
from hub.models import Hub
from paper.related_models.paper_model import Paper
from reputation.related_models.bounty import Bounty
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.views.researchhub_unified_document_views import get_user_votes

from .models import FeedEntry
from .serializers import FeedEntrySerializer


class FeedPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


DEFAULT_CACHE_TIMEOUT = 60 * 30  # 30 minutes


class FeedViewSet(viewsets.ModelViewSet):
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
                return Response(cached_response)

        response = super().list(request, *args, **kwargs)

        if use_cache:
            # cache response
            cache.set(cache_key, response.data, timeout=DEFAULT_CACHE_TIMEOUT)

        # Get votes for each item in the feed
        if request.user.is_authenticated:
            self._add_user_votes_to_response(request.user, response.data)

        return response

    def _add_user_votes_to_response(self, user, response_data):
        """
        Add user votes to feed items in the response data.

        Args:
            user: The authenticated user
            response_data: The response data containing feed items
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
                        item["content_object"]["user_vote"] = paper_votes_map[paper_id]

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
                        item["content_object"]["user_vote"] = post_votes_map[post_id]

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
                        item["content_object"]["user_vote"] = comment_votes_map[
                            comment_id
                        ]
                # Handle bounties with comments
                elif item.get("content_type") == bounty_type_str and item[
                    "content_object"
                ].get("comment"):
                    comment_id = int(item["content_object"]["comment"]["id"])
                    if comment_id in comment_votes_map:
                        item["content_object"]["comment"]["user_vote"] = (
                            comment_votes_map[comment_id]
                        )

    def _get_cache_key(self, request: Request) -> str:
        feed_view = request.query_params.get("feed_view", "latest")
        hub_slug = request.query_params.get("hub_slug")
        user_id = request.user.id if request.user.is_authenticated else None

        page = request.query_params.get("page", "1")
        page_size = request.query_params.get(
            self.pagination_class.page_size_query_param,
            str(self.pagination_class.page_size),
        )

        hub_part = hub_slug or "all"
        user_part = "none" if feed_view == "popular" else f"{user_id or 'anonymous'}"
        pagination_part = f"{page}-{page_size}"

        return f"feed:{feed_view}:{hub_part}:{user_part}:{pagination_part}"

    def get_queryset(self):
        """
        Filter feed entries based on the feed view ('following' or 'latest')
        and additional filters. For 'following' view, show items related to what
        user follows. For 'latest' view, show all items. Ensure that the result
        contains only the most recent entry per (content_type, object_id),
        ordered globally by the most recent action_date.
        """
        feed_view = self.request.query_params.get("feed_view", "latest")
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
        )

        # Apply following filter if feed_view is 'following' and user is authenticated
        if feed_view == "following" and self.request.user.is_authenticated:
            following = self.request.user.following.all()
            if following.exists():
                queryset = queryset.filter(
                    parent_content_type_id__in=following.values("content_type"),
                    parent_object_id__in=following.values("object_id"),
                )

        if feed_view == "popular":
            top_unified_docs = ResearchhubUnifiedDocument.objects.filter(
                is_removed=False
            ).order_by("-hot_score")

            # Apply any additional filters
            if hub_slug:
                try:
                    hub = Hub.objects.get(slug=hub_slug)
                except Hub.DoesNotExist:
                    return Response(
                        {"error": "Hub not found"}, status=status.HTTP_404_NOT_FOUND
                    )

                top_unified_docs = top_unified_docs.filter(hubs=hub)

            # Since there can be multiple feed entries per unified document,
            # we need to select the most recent entry for each document
            # Get the IDs of the most recent feed entry for each unified document
            latest_entries_subquery = (
                FeedEntry.objects.filter(unified_document__in=top_unified_docs)
                .values("unified_document")
                .annotate(
                    latest_id=models.Max("id"), latest_date=models.Max("action_date")
                )
                .values_list("latest_id", flat=True)
            )

            queryset = queryset.filter(
                id__in=Subquery(latest_entries_subquery), unified_document__isnull=False
            ).order_by("-unified_document__hot_score")

            return queryset

        # For other feed views (latest, following with hub filter)
        # Apply hub filter if hub_id is provided
        if hub_slug:
            try:
                hub = Hub.objects.get(slug=hub_slug)
            except Hub.DoesNotExist:
                return Response(
                    {"error": "Hub not found"}, status=status.HTTP_404_NOT_FOUND
                )

            hub_content_type = ContentType.objects.get_for_model(Hub)
            queryset = queryset.filter(
                parent_content_type=hub_content_type, parent_object_id=hub.id
            )

        sub_qs = queryset.order_by(
            "content_type_id", "object_id", "-action_date"
        ).distinct("content_type_id", "object_id")

        final_qs = queryset.filter(pk__in=sub_qs.values("pk")).order_by("-action_date")

        return final_qs
