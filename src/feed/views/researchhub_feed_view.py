from rest_framework.viewsets import ModelViewSet

from feed.clients.personalize_client import PersonalizeClient
from feed.feed_config import FEED_CONFIG
from feed.filtering import FeedFilteringBackend
from feed.models import FeedEntry
from feed.ordering import FeedOrderingBackend
from feed.serializers import FeedEntrySerializer
from feed.views.common import FeedPagination
from feed.views.feed_view_mixin import FeedViewMixin


class ResearchHubFeedPagination(FeedPagination):
    page_size = 30


class ResearchHubFeed(FeedViewMixin, ModelViewSet):
    queryset = FeedEntry.objects.all()
    serializer_class = FeedEntrySerializer
    permission_classes = []
    pagination_class = ResearchHubFeedPagination
    filter_backends = [FeedFilteringBackend, FeedOrderingBackend]

    def dispatch(self, request, *args, **kwargs):
        self.personalize_client = kwargs.pop("personalize_client", PersonalizeClient())
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
            cache_key_feed_type="researchhub",
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
