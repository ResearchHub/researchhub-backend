from django.core.cache import cache
from django.db.models import Case, IntegerField, Value, When
from rest_framework.viewsets import ModelViewSet

from feed.clients.personalize_client import PersonalizeClient
from feed.feed_config import FEED_CONFIG, FEED_DEFAULTS
from feed.filtering import FeedFilteringBackend
from feed.models import FeedEntry
from feed.ordering import FeedOrderingBackend
from feed.serializers import FeedEntrySerializer
from feed.views.common import FeedPagination
from feed.views.feed_view_mixin import FeedViewMixin
from hub.models import Hub


class ResearchHubFeedPagination(FeedPagination):
    page_size = 30


class ResearchHubFeed(FeedViewMixin, ModelViewSet):
    queryset = FeedEntry.objects.all()
    serializer_class = FeedEntrySerializer
    permission_classes = []
    pagination_class = ResearchHubFeedPagination
    filter_backends = [
        FeedFilteringBackend,
        FeedOrderingBackend,
    ]

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

        supports_diversification = feed_config.get("supports_diversification", False)
        diversify_param = request.query_params.get("diversify", "false").lower()
        page = int(request.query_params.get("page", "1"))

        num_pages_to_diversify = FEED_DEFAULTS["diversification"][
            "num_pages_to_diversify"
        ]
        should_diversify = (
            supports_diversification
            and diversify_param == "true"
            and page <= num_pages_to_diversify
        )

        if should_diversify:
            return self._get_diversified_list_response(request)

        use_cache_for_feed = feed_config.get("use_cache", False)
        return self.get_cached_list_response(
            request,
            use_cache_config=use_cache_for_feed,
            cache_key_feed_type="researchhub",
        )

    def get_queryset(self):
        qs = self.queryset
        if id(qs) != id(ResearchHubFeed.queryset):
            return qs
        return self._get_optimized_queryset(qs)

    def _get_optimized_queryset(self, base_queryset):
        return base_queryset.select_related(
            "content_type",
            "user",
            "user__author_profile",
            "user__userverification",
            "unified_document",
        ).prefetch_related("unified_document__hubs")

    def _get_diversified_list_response(self, request):
        cache_key = self._get_diversified_cache_key(request)
        cached_data = cache.get(cache_key)

        if cached_data:
            return self.paginate_cached_results(
                request, cached_data, self.pagination_class
            )

        self._diversify_queryset()
        self._is_diversified = True

        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        full_data = serializer.data

        if request.user.is_authenticated:
            response_data = {"results": full_data}
            self.add_user_votes_to_response(request.user, response_data)
            full_data = response_data["results"]

        cache.set(cache_key, full_data, timeout=self.DEFAULT_CACHE_TIMEOUT)

        return self.paginate_cached_results(request, full_data, self.pagination_class)

    def _diversify_queryset(self):
        queryset = self.filter_queryset(self.get_queryset())
        num_pages_to_diversify = FEED_DEFAULTS["diversification"][
            "num_pages_to_diversify"
        ]
        batch_size = self.pagination_class.page_size * num_pages_to_diversify
        batch_entries = list(queryset[:batch_size])

        if not batch_entries:
            return

        diversified_entries = self._diversify_batch(batch_entries)
        entry_ids = [entry.id for entry in diversified_entries]

        preserved_order = [
            When(id=entry_id, then=Value(idx)) for idx, entry_id in enumerate(entry_ids)
        ]

        self.queryset = self._get_optimized_queryset(
            FeedEntry.objects.filter(id__in=entry_ids)
        ).order_by(Case(*preserved_order, output_field=IntegerField()))

    def _diversify_batch(self, entries):
        config = FEED_DEFAULTS["diversification"]
        max_consecutive = config["max_consecutive"]
        reinject_interval = config["reinject_interval"]

        diversified = []
        deferred = []
        last_group = None
        current_consecutive = 0

        for entry in entries:
            group = self._get_subcategory(entry)

            if group == last_group:
                current_consecutive += 1
            else:
                current_consecutive = 1
                last_group = group

            if current_consecutive <= max_consecutive:
                diversified.append(entry)

                if len(diversified) % reinject_interval == 0 and deferred:
                    reinjected = deferred.pop(0)
                    diversified.append(reinjected)
                    last_group = self._get_subcategory(reinjected)
                    current_consecutive = 1
            else:
                deferred.append(entry)

        diversified.extend(deferred)
        return diversified

    def _get_subcategory(self, entry):
        if not entry.unified_document:
            return None

        subcategory = entry.unified_document.hubs.filter(
            namespace=Hub.Namespace.SUBCATEGORY
        ).first()

        return subcategory.id if subcategory else None

    def _get_diversified_cache_key(self, request):
        feed_view = request.query_params.get("feed_view", "popular")
        hub_slug = request.query_params.get("hub_slug", "all")
        ordering = request.query_params.get("ordering", "default")
        user_id = request.user.id if request.user.is_authenticated else "anon"

        return f"researchhub_diversified:{feed_view}:{user_id}:{hub_slug}:{ordering}"
