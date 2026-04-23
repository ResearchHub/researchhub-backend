from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from feed.views.common import FeedPagination

FUNDING_FEED_MAX_CACHED_PAGE = 3

FUNDING_FEED_ORDERINGS = [
    "latest",
    "newest",
    "best",
    "upvotes",
    "most_applicants",
    "amount_raised",
]

FUNDING_FEED_VIEWS = ("popular", "latest")
FUNDING_SOURCE_PARTS = ("all", "researchhub")
FUNDING_HUB_PARTS = ("all",)
FUNDRAISE_STATUS_PARTS: tuple[str | None, ...] = (None, "OPEN", "CLOSED")
INCLUDE_ENDED_VALUES = ("true", "false")


def _funding_invalidation_request(query_params: dict[str, str]) -> Request:
    factory = APIRequestFactory()
    wsgi_request = factory.get("/api/funding_feed/", query_params)
    drf_request = Request(wsgi_request)
    drf_request.user = AnonymousUser()
    return drf_request


class FundingCacheMixin:
    """Mixin for :class:`~feed.views.funding_feed_view.FundingFeedViewSet` cache helpers."""

    @staticmethod
    def invalidate_funding_feed_cache() -> None:
        """
        Delete cached funding-feed list responses (pages 1–``FUNDING_FEED_MAX_CACHED_PAGE``).

        Only keys that can be written when ``FundingFeedViewSet.list`` uses the cache
        branch are targeted. Hub-specific ``?hub_slug=`` keys (other than default) are
        not enumerated; they expire via TTL.
        """
        # Local import avoids circular import: funding_feed_view loads this module first.
        from feed.views.funding_feed_view import FundingFeedViewSet

        view = FundingFeedViewSet()
        view.pagination_class = FeedPagination
        page_size = str(FeedPagination.page_size)
        keys: list[str] = []
        for feed_view in FUNDING_FEED_VIEWS:
            for hub_part in FUNDING_HUB_PARTS:
                for source_part in FUNDING_SOURCE_PARTS:
                    for page_num in range(1, FUNDING_FEED_MAX_CACHED_PAGE + 1):
                        for fundraise_status in FUNDRAISE_STATUS_PARTS:
                            for ordering in FUNDING_FEED_ORDERINGS:
                                for include_ended in INCLUDE_ENDED_VALUES:
                                    params: dict[str, str] = {
                                        "page": str(page_num),
                                        "page_size": page_size,
                                        "feed_view": feed_view,
                                    }
                                    if hub_part != "all":
                                        params["hub_slug"] = hub_part
                                    if source_part != "all":
                                        params["source"] = source_part
                                    if fundraise_status:
                                        params["fundraise_status"] = fundraise_status
                                    if ordering != "latest":
                                        params["ordering"] = ordering
                                    if include_ended != "true":
                                        params["include_ended"] = include_ended
                                    req = _funding_invalidation_request(params)
                                    keys.append(view.get_cache_key(req, "funding"))
        cache.delete_many(list(dict.fromkeys(keys)))
