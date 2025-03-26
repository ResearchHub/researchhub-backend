"""
Standard feed view for ResearchHub.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from rest_framework import status, viewsets
from rest_framework.response import Response

from hub.models import Hub
from paper.related_models.paper_model import Paper
from researchhub_document.models import ResearchhubUnifiedDocument

from ..models import FeedEntry
from ..serializers import FeedEntrySerializer
from .common import (
    DEFAULT_CACHE_TIMEOUT,
    FeedPagination,
    add_user_votes_to_response,
    get_cache_key,
)


class FeedViewSet(viewsets.ModelViewSet):
    """
    ViewSet for accessing the main feed of ResearchHub activities.
    Supports filtering by hub, following status, and sorting by popularity.
    """

    serializer_class = FeedEntrySerializer
    permission_classes = []
    pagination_class = FeedPagination

    def list(self, request, *args, **kwargs):
        page = request.query_params.get("page", "1")
        page_num = int(page)
        cache_key = get_cache_key(request)
        use_cache = page_num < 4

        if use_cache:
            # try to get cached response
            cached_response = cache.get(cache_key)
            if cached_response:
                if request.user.is_authenticated:
                    add_user_votes_to_response(request.user, cached_response)
                return Response(cached_response)

        response = super().list(request, *args, **kwargs)

        if use_cache:
            # cache response
            cache.set(cache_key, response.data, timeout=DEFAULT_CACHE_TIMEOUT)

        if request.user.is_authenticated:
            add_user_votes_to_response(request.user, response.data)

        return response

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
        source = self.request.query_params.get("source", "all")

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
            )
        )

        # Apply source filter
        # If source is 'researchhub', then only show items that are related to
        # ResearchHub content. Since we don't have a dedicated field for this,
        # a simplified heuristic is to filter out papers (papers are ingested via
        # OpenAlex and do not originate on ResearchHub).
        if source == "researchhub":
            paper_content_type = ContentType.objects.get_for_model(Paper)
            queryset = queryset.exclude(content_type_id=paper_content_type.id)

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

            queryset = queryset.filter(unified_document__in=top_unified_docs)

            sub_qs = queryset.order_by(
                "content_type_id", "object_id", "-action_date"
            ).distinct("content_type_id", "object_id")

            final_qs = queryset.filter(pk__in=sub_qs.values("pk")).order_by(
                "-unified_document__hot_score"
            )

            return final_qs

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
