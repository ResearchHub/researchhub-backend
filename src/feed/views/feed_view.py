from django.conf import settings
from django.core.cache import cache
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from feed.feed_config import FEED_CONFIG, FEED_DEFAULTS
from feed.filtering import FeedFilteringBackend
from feed.models import FeedEntry
from feed.ordering import FeedOrderingBackend
from feed.serializers import FeedEntrySerializer
from feed.views.common import FeedPagination as BaseFeedPagination
from feed.views.feed_view_mixin import FeedViewMixin
from utils.throttles import FeedRecommendationRefreshThrottle


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

        return self._get_feed_response(request, feed_view)

    def _get_personalized_response(self, request):
        """Handle personalized feed with partial caching."""
        response = super(FeedViewSet, self).list(request)

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response.data)

        cache_status = (
            "partial-cache-hit"
            if self.personalize_feed_service.cache_hit
            else "partial-cache-miss"
        )
        response["RH-Cache"] = self._with_auth_suffix(request, cache_status)
        return response

    def _get_feed_response(self, request, feed_view):
        """Handle feed response with optional caching."""
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
        """Add X-Feed-Source header for popular feed."""
        if feed_view == "popular":
            feed_source = getattr(self, "_feed_source", None)
            if feed_source:
                response["X-Feed-Source"] = feed_source

    def get_queryset(self):
        queryset = FeedEntry.objects.all()

        queryset = queryset.select_related(
            "content_type",
            "user",
            "user__author_profile",
            "user__userverification",
        )

        return queryset
