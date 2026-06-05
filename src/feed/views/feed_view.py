from typing import NamedTuple

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db.models import QuerySet
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from feed.feed_config import FEED_CONFIG, FEED_DEFAULTS
from feed.filtering import FeedFilteringBackend
from feed.models import FeedEntry
from feed.ordering import FeedOrderingBackend
from feed.serializers import FeedEntrySerializer
from feed.views.common import FeedPagination as BaseFeedPagination
from feed.views.feed_view_mixin import FeedViewMixin
from paper.related_models.paper_model import Paper
from paper.related_models.paper_version import PaperVersion
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.permissions import IsModerator
from utils.throttles import FeedRecommendationRefreshThrottle


class PendingSource(NamedTuple):
    queryset: QuerySet
    content_type: ContentType
    author_attr: str


class FeedPagination(BaseFeedPagination):
    page_size = 30


class FeedViewSet(FeedViewMixin, ModelViewSet):
    queryset = FeedEntry.objects.all()
    serializer_class = FeedEntrySerializer
    permission_classes = []
    pagination_class = FeedPagination
    filter_backends = [FeedFilteringBackend, FeedOrderingBackend]
    throttle_classes = [FeedRecommendationRefreshThrottle]

    def dispatch(self, request, *args, **kwargs):
        from personalize.services.feed_service import FeedService

        self.personalize_feed_service = FeedService()
        return super().dispatch(request, *args, **kwargs)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())

        if hasattr(self, "_personalize_recommendation_id"):
            context["recommendation_id"] = self._personalize_recommendation_id

        return context

    def list(self, request, *args, **kwargs):
        feed_view = request.query_params.get("feed_view", "popular")

        if feed_view == "personalized":
            return self._get_personalized_response(request)

        return self._get_non_personalized_feed_response(request, feed_view)

    @action(detail=False, methods=["get"], permission_classes=[IsModerator])
    def pending_moderation(self, request: Request) -> Response:
        """Serve works awaiting moderation, rendered in the standard feed shape.

        Pending works have no persisted FeedEntry (publication is deferred until
        approval), so feed entries are built on the fly from the source models --
        the same approach the journal feed uses. Moderator-only.
        """
        content_type = (request.query_params.get("content_type") or "").upper()
        source = self._pending_moderation_source(content_type)
        if source is None:
            return Response(
                {"message": "Unsupported content_type."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        page = self.paginate_queryset(source.queryset)
        feed_entries = [
            self.build_unsaved_feed_entry(
                item, source.content_type, getattr(item, source.author_attr)
            )
            for item in page
        ]
        serializer = self.get_serializer(feed_entries, many=True)
        return self.get_paginated_response(serializer.data)

    def _pending_moderation_source(self, content_type: str) -> PendingSource | None:
        """Map a moderation tab's content_type to its pending queryset."""
        if content_type == "PAPER":
            # Only ResearchHub-journal submissions enter the PENDING moderation
            # state, so the moderation paper tab scopes to them the same way the
            # journal feed does (version__journal=RESEARCHHUB). Non-journal papers
            # are never pending and therefore never need to surface here.
            queryset = (
                Paper.objects.filter(
                    status=Paper.PENDING,
                    is_removed=False,
                    version__journal=PaperVersion.RESEARCHHUB,
                )
                .select_related(
                    "uploaded_by",
                    "uploaded_by__author_profile",
                    "unified_document",
                    "version",
                )
                .prefetch_related("unified_document__hubs")
                .order_by("-created_date")
            )
            return PendingSource(queryset, self._paper_content_type, "uploaded_by")

        post_document_type = {
            "PREREGISTRATION": PREREGISTRATION,
            "POST": DISCUSSION,
        }.get(content_type)
        if post_document_type is None:
            return None

        queryset = (
            ResearchhubPost.objects.filter(
                document_type=post_document_type, status=ResearchhubPost.PENDING
            )
            .select_related(
                "created_by", "created_by__author_profile", "unified_document"
            )
            .prefetch_related("unified_document__hubs")
            .order_by("-created_date")
        )
        return PendingSource(queryset, self._post_content_type, "created_by")

    def _get_personalized_response(self, request):
        """Handle personalized feed (Personalize recommendations)."""
        response = super(FeedViewSet, self).list(request)

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response.data)

        # Add feed source header - may be overridden on Personalize error
        feed_source = getattr(self, "_feed_source", "aws-personalize")
        response["RH-Feed-Source"] = feed_source

        cache_status = (
            "partial-cache-hit"
            if self.personalize_feed_service.cache_hit
            else "partial-cache-miss"
        )
        response["RH-Cache"] = self._with_auth_suffix(request, cache_status)
        return response

    def _get_non_personalized_feed_response(self, request, feed_view):
        feed_config = FEED_CONFIG.get(feed_view, {})
        use_cache = self._should_use_cache(request, feed_config)
        cache_key = self.get_cache_key(request, feed_type="researchhub")

        # Try cache first
        if use_cache:
            cached_response = cache.get(cache_key)
            if cached_response:
                if request.user.is_authenticated:
                    self.add_user_votes_to_response(request.user, cached_response)
                response = Response(cached_response)
                response["RH-Cache"] = self._with_auth_suffix(request, "hit")
                self._add_feed_source_header(response, feed_view)
                return response

        # Fetch fresh data
        response = super(FeedViewSet, self).list(request)

        if use_cache:
            cache.set(cache_key, response.data, timeout=self.DEFAULT_CACHE_TIMEOUT)

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response.data)

        response["RH-Cache"] = self._with_auth_suffix(request, "miss")
        self._add_feed_source_header(response, feed_view)
        return response

    def _should_use_cache(self, request, feed_config):
        # Feed/ordering config check
        if not self._feed_allows_caching(request, feed_config):
            return False

        # Environment check
        if not (settings.TESTING or settings.CLOUD):
            return False

        # Health check override
        disable_token = request.query_params.get("disable_cache")
        if disable_token == settings.HEALTH_CHECK_TOKEN:
            return False

        # Page limit check
        page_num = int(request.query_params.get("page", "1"))
        if page_num > FEED_DEFAULTS["cache"]["num_pages_to_cache"]:
            return False

        return True

    def _feed_allows_caching(self, request, feed_config):
        """
        Check if feed type/ordering allows caching (from config).

        - aws_trending: No full-page cache (IDs cached separately in FeedService)
        - hot_score_v2/hot_score: Full-page cache enabled
        """
        cache_by_ordering = feed_config.get("cache_by_ordering")
        if cache_by_ordering:
            ordering = request.query_params.get("ordering")
            allowed = feed_config.get("allowed_sorts", [])
            effective_ordering = (
                ordering if ordering in allowed else (allowed[0] if allowed else None)
            )
            return cache_by_ordering.get(effective_ordering, False)

        # Fall back to simple use_cache setting
        return feed_config.get("use_cache", False)

    def _with_auth_suffix(self, request, status):
        """Add auth suffix to cache status."""
        return status + (" (auth)" if request.user.is_authenticated else "")

    def _add_feed_source_header(self, response, feed_view):
        """Add RH-Feed-Source header based on feed type."""
        if feed_view == "popular":
            feed_source = getattr(self, "_feed_source", None)
            if feed_source:
                response["RH-Feed-Source"] = feed_source
        elif feed_view == "following":
            response["RH-Feed-Source"] = "rh-following"
        elif feed_view == "latest":
            response["RH-Feed-Source"] = "rh-latest"

    def get_queryset(self):
        queryset = FeedEntry.objects.all()

        queryset = queryset.select_related(
            "content_type",
            "user",
            "user__author_profile",
            "user__userverification",
        )

        return queryset
