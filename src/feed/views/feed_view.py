"""
Standard feed view for ResearchHub.
"""

import logging

from django.conf import settings
from django.core.cache import cache
from django.db.models import Case, IntegerField, Value, When
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from feed.clients.personalize_client import PersonalizeClient
from feed.views.feed_view_mixin import FeedViewMixin
from hub.models import Hub

from ..models import FeedEntry
from ..serializers import FeedEntrySerializer
from .common import FeedPagination

logger = logging.getLogger(__name__)


class FeedViewSet(FeedViewMixin, ModelViewSet):
    """
    ViewSet for accessing the main feed of ResearchHub activities.
    Supports filtering by hub, following status, and sorting by popularity.
    """

    serializer_class = FeedEntrySerializer
    permission_classes = []
    pagination_class = FeedPagination
    cache_enabled = settings.TESTING or settings.CLOUD

    def dispatch(self, request, *args, **kwargs):
        self.personalize_client = kwargs.pop("personalize_client", PersonalizeClient())
        return super().dispatch(request, *args, **kwargs)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    def list(self, request, *args, **kwargs):
        page = request.query_params.get("page", "1")
        page_num = int(page)
        cache_key = self.get_cache_key(request)

        disable_cache_token = request.query_params.get("disable_cache")
        force_disable_cache = disable_cache_token == settings.HEALTH_CHECK_TOKEN
        use_cache = not force_disable_cache and self.cache_enabled and page_num < 4

        if use_cache:
            # try to get cached response
            cached_response = cache.get(cache_key)
            if cached_response:
                if request.user.is_authenticated:
                    self.add_user_votes_to_response(request.user, cached_response)
                response = Response(cached_response)
                response["RH-Cache"] = "hit" + (
                    " (auth)" if request.user.is_authenticated else ""
                )
                return response

        response = super().list(request, *args, **kwargs)

        if use_cache:
            # cache response
            cache.set(cache_key, response.data, timeout=self.DEFAULT_CACHE_TIMEOUT)

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response.data)

        response["RH-Cache"] = "miss" + (
            " (auth)" if request.user.is_authenticated else ""
        )
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
        sort_by = self.request.query_params.get("sort_by", "latest")
        hot_score_version = self.request.query_params.get("hot_score_version", "v1")
        hot_score_field = "hot_score_v2" if hot_score_version == "v2" else "hot_score"

        # Use FeedEntry for all queries, sorted by hot_score or action_date
        queryset = FeedEntry.objects.all()

        # Apply sorting based on feed_view and sort_by
        if feed_view == "popular" or (
            feed_view == "following" and sort_by == "hot_score"
        ):
            queryset = queryset.order_by(f"-{hot_score_field}")
        else:
            queryset = queryset.order_by("-action_date")

        queryset = queryset.select_related(
            "content_type",
            "user",
            "user__author_profile",
            "user__userverification",
        )

        # Apply source filter
        # If source is 'researchhub', then only show items that are related to
        # ResearchHub content. Since we don't have a dedicated field for this,
        # a simplified heuristic is to filter out papers (papers are ingested via
        # OpenAlex and do not originate on ResearchHub).
        if source == "researchhub":
            queryset = queryset.exclude(content_type=self._paper_content_type)

        # Apply following filter only for "following" view
        if feed_view == "following":
            followed_hub_ids = self.get_followed_hub_ids()
            if followed_hub_ids:
                queryset = queryset.filter(
                    hubs__id__in=followed_hub_ids,
                )

            # Only show paper and post for all following views
            queryset = queryset.filter(
                content_type__in=[
                    self._paper_content_type,
                    self._post_content_type,
                ]
            )

        # Handle both popular view and following view with hot_score sorting
        if feed_view == "popular" or (
            feed_view == "following" and sort_by == "hot_score"
        ):
            # Only show paper and post for both popular and following with hot_score
            queryset = queryset.filter(
                content_type__in=[
                    self._paper_content_type,
                    self._post_content_type,
                ]
            )

            if hub_slug:
                try:
                    hub = Hub.objects.get(slug=hub_slug)
                except Hub.DoesNotExist:
                    return Response(
                        {"error": "Hub not found"}, status=status.HTTP_404_NOT_FOUND
                    )

                queryset = queryset.filter(
                    hubs__in=[hub],
                )

            return queryset.distinct()

        # Latest / Following

        # For other feed views (latest, following with hub filter)
        # Apply hub filter if hub_id is provided
        if hub_slug:
            try:
                hub = Hub.objects.get(slug=hub_slug)
            except Hub.DoesNotExist:
                return Response(
                    {"error": "Hub not found"}, status=status.HTTP_404_NOT_FOUND
                )

            queryset = queryset.filter(
                hubs__in=[hub],
            )

        return queryset.distinct()

    def _get_queryset_for_personalized(self, item_ids):
        """
        Get FeedEntry queryset for personalized recommendations.

        """
        if not item_ids:
            return FeedEntry.objects.none()

        item_ids = [int(item_id) for item_id in item_ids]

        preserved_order = [
            When(unified_document_id=item_id, then=Value(idx))
            for idx, item_id in enumerate(item_ids)
        ]

        queryset = (
            FeedEntry.objects.filter(unified_document_id__in=item_ids)
            .order_by(Case(*preserved_order, output_field=IntegerField()))
            .select_related(
                "content_type",
                "user",
                "user__author_profile",
                "user__userverification",
            )
            .distinct()
        )

        return queryset

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def personalized(self, request):
        """
        Get personalized feed entries for the authenticated user using AWS Personalize.
        """
        try:
            page_size = int(
                request.query_params.get("page_size", self.pagination_class.page_size)
            )
            # Request more items to account for items to avoid multiple requests
            num_results = min(page_size * 3, 100)

            item_ids = self.personalize_client.get_recommendations_for_user(
                user_id=request.user.id,
                filter=request.query_params.get("filter"),
                num_results=num_results,
            )

            queryset = self._get_queryset_for_personalized(item_ids)

            page = self.paginate_queryset(queryset)
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)

            self.add_user_votes_to_response(request.user, response.data)
            return response

        except Exception as e:
            logger.error(
                f"Error getting personalized feed for user {request.user.id}: {str(e)}"
            )
            return Response(
                {"error": "Failed to retrieve personalized recommendations"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
