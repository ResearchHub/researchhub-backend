from django.core.cache import cache
from rest_framework.filters import BaseFilterBackend

from feed.feed_visibility import exclude_hidden_feed_entries
from hub.models import Hub

# Allowed preprint hub slugs for feed filtering
ALLOWED_PREPRINT_HUB_SLUGS = frozenset({"biorxiv", "arxiv", "chemrxiv", "medrxiv"})
PREPRINT_HUB_IDS_CACHE_KEY = "feed:allowed_preprint_hub_ids"
PREPRINT_HUB_IDS_CACHE_TTL = 86400  # 24 hours


def _get_allowed_preprint_hub_ids() -> tuple[int, ...]:
    """
    Get cached hub IDs for allowed preprint sources.
    """
    hub_ids = cache.get(PREPRINT_HUB_IDS_CACHE_KEY)
    if hub_ids is None:
        hub_ids = tuple(
            Hub.objects.filter(slug__in=ALLOWED_PREPRINT_HUB_SLUGS).values_list(
                "id", flat=True
            )
        )
        cache.set(
            PREPRINT_HUB_IDS_CACHE_KEY, hub_ids, timeout=PREPRINT_HUB_IDS_CACHE_TTL
        )
    return hub_ids


class FeedFilteringBackend(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        queryset = exclude_hidden_feed_entries(queryset)

        # Exclude entries that don't allow PDF display
        queryset = queryset.exclude(pdf_copyright_allows_display=False)

        # Global filter: Only show papers from allowed preprint sources
        # This applies to all feed views (papers must be from biorxiv, arxiv, etc.)
        queryset = self._filter_by_allowed_preprint_hubs(queryset, view)

        feed_view = request.query_params.get("feed_view", "popular")

        if feed_view == "following":
            return self._filter_following(request, queryset, view)
        elif feed_view == "latest":
            return self._filter_latest(request, queryset, view)
        else:
            return self._filter_popular(request, queryset, view)

    def _filter_latest(self, request, queryset, view):
        hub_slug = request.query_params.get("hub_slug")
        if hub_slug:
            # Additionally filter by user-specified hub
            queryset = self._filter_by_hub(hub_slug, queryset)

        return queryset

    def _filter_following(self, request, queryset, view):
        # Preprint hub filter already applied globally in filter_queryset
        if not request.user.is_authenticated:
            return queryset.none()

        followed_hub_ids = view.get_followed_hub_ids()
        if followed_hub_ids:
            # SHIM: Uses unified_document.hubs (FeedEntry.hubs may be out of sync)
            queryset = queryset.filter(unified_document__hubs__id__in=followed_hub_ids)
        else:
            return queryset.none()

        return queryset

    def _filter_popular(self, request, queryset, view):
        hub_slug = request.query_params.get("hub_slug")
        if hub_slug:
            queryset = self._filter_by_hub(hub_slug, queryset)

        view._feed_source = "rh-popular"
        return queryset

    def _filter_by_allowed_preprint_hubs(self, queryset, view):
        """
        Filter queryset to only include papers from allowed preprint hubs.
        Papers must have at least one hub from: biorxiv, arxiv, chemrxiv, medrxiv.

        Uses unified_document.hubs (FeedEntry.hubs may be out of sync).
        """
        preprint_hub_ids = _get_allowed_preprint_hub_ids()
        return queryset.filter(
            content_type=view._paper_content_type,
            unified_document__hubs__id__in=preprint_hub_ids,
        )

    def _filter_by_hub(self, hub_slug, queryset):
        try:
            hub = Hub.objects.get(slug=hub_slug)
        except Hub.DoesNotExist:
            return queryset.none()

        # SHIM: Uses unified_document.hubs (FeedEntry.hubs may be out of sync)
        return queryset.filter(unified_document__hubs__in=[hub])
