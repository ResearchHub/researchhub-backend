from django.conf import settings
from django.core.cache import cache
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from feed.feed_config import FEED_CONFIG, FEED_DEFAULTS
from feed.filtering import FeedFilteringBackend
from feed.models import FeedEntry
from feed.ordering import FeedOrderingBackend
from feed.serializers import FeedEntrySerializer
from feed.views.common import FeedPagination
from feed.views.feed_view_mixin import FeedViewMixin


class ResearchHubFeedPagination(FeedPagination):
    page_size = 30


class ResearchHubFeedViewSet(FeedViewMixin, ModelViewSet):
    queryset = FeedEntry.objects.all()
    serializer_class = FeedEntrySerializer
    permission_classes = []
    pagination_class = ResearchHubFeedPagination
    filter_backends = [FeedFilteringBackend, FeedOrderingBackend]

    def dispatch(self, request, *args, **kwargs):
        from feed.services import PersonalizeFeedService

        self.personalize_feed_service = PersonalizeFeedService()
        return super().dispatch(request, *args, **kwargs)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    def list(self, request, *args, **kwargs):
        feed_view = request.query_params.get("feed_view", "popular")
        feed_config = FEED_CONFIG.get(feed_view, {})
        use_cache_for_feed = feed_config.get("use_cache", False)

        return self.get_cached_list_response(
            request,
            use_cache_config=use_cache_for_feed,
        )

    def get_queryset(self):
        queryset = FeedEntry.objects.all()

        queryset = queryset.select_related(
            "content_type",
            "user",
            "user__author_profile",
            "user__userverification",
        )

        return queryset

    def get_cached_list_response(
        self,
        request,
        use_cache_config=True,
    ):
        feed_view = request.query_params.get("feed_view", "popular")

        if feed_view == "personalized":
            response = super(ResearchHubFeedViewSet, self).list(request)
            if request.user.is_authenticated:
                self.add_user_votes_to_response(request.user, response.data)

            cache_status = (
                "partial-cache-hit"
                if self.personalize_feed_service.cache_hit
                else "partial-cache-miss"
            )
            print(f"cache_status: {cache_status}")
            response["RH-Cache"] = cache_status + (
                " (auth)" if request.user.is_authenticated else ""
            )
            return response

        page = request.query_params.get("page", "1")
        page_num = int(page)
        cache_key = self.get_cache_key(request, feed_type="researchhub")

        disable_cache_token = request.query_params.get("disable_cache")
        force_disable_cache = disable_cache_token == settings.HEALTH_CHECK_TOKEN

        cache_enabled = settings.TESTING or settings.CLOUD
        num_pages_to_cache = FEED_DEFAULTS["cache"]["num_pages_to_cache"]

        use_cache = (
            not force_disable_cache
            and cache_enabled
            and use_cache_config
            and page_num <= num_pages_to_cache
        )

        if use_cache:
            cached_response = cache.get(cache_key)
            if cached_response:
                if request.user.is_authenticated:
                    self.add_user_votes_to_response(request.user, cached_response)
                response = Response(cached_response)
                response["RH-Cache"] = "hit" + (
                    " (auth)" if request.user.is_authenticated else ""
                )
                return response

        response = super(ResearchHubFeedViewSet, self).list(request)

        if use_cache:
            cache.set(cache_key, response.data, timeout=self.DEFAULT_CACHE_TIMEOUT)

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response.data)

        response["RH-Cache"] = "miss" + (
            " (auth)" if request.user.is_authenticated else ""
        )
        return response
