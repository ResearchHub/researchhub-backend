from django.conf import settings
from django.core.cache import cache
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from analytics.models import UserInteractions
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
            # Resolve actual feed strategy based on user's interaction history
            resolved_strategy = self._resolve_personalized_feed_strategy(request)
            self._resolved_feed_view = resolved_strategy

            if resolved_strategy == "personalized":
                return self._get_personalized_response(request)
            else:
                # Cold-start: route to following feed
                return self._get_following_response(request)

        return self._get_feed_response(request, feed_view)

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

    def _get_following_response(self, request):
        """Handle following feed (cold-start fallback for personalized)."""
        response = super(FeedViewSet, self).list(request)

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response.data)

        # Mark as following feed source (cold-start fallback)
        response["RH-Feed-Source"] = "rh-following"
        response["RH-Cache"] = self._with_auth_suffix(request, "miss")
        return response

    def _get_feed_response(self, request, feed_view):
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

    def _resolve_personalized_feed_strategy(self, request) -> str:
        """
        "personalized" or "following" feed strategy based on interaction count.
        """
        if not request.user.is_authenticated:
            return "following"

        user_id = request.user.id
        personalized_config = FEED_CONFIG["personalized"]
        min_interactions = personalized_config["min_interactions_for_personalize"]

        cache_key = f"interaction_count:{user_id}"
        interaction_count = cache.get(cache_key)
        if interaction_count is None:
            interaction_count = UserInteractions.objects.filter(user_id=user_id).count()
            cache.set(cache_key, interaction_count, timeout=300)

        return "personalized" if interaction_count >= min_interactions else "following"
