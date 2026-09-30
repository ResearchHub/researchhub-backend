import logging

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from feed.cache_segment import FEED_CACHE_MAX_CACHED_PAGE, FEED_CACHE_PAGE_SIZE
from feed.funding_feed_cache import (
    FUNDING_FEED_WARM_COMPLETED_STATUS,
    FUNDING_FEED_WARM_ORDERINGS,
    FUNDING_FEED_WARM_SEGMENTS,
)

logger = logging.getLogger(__name__)


class FundingCacheMixin:
    """
    Mixin for :class:`~feed.views.funding_feed_view.FundingFeedViewSet` cache helpers.
    """

    @staticmethod
    def invalidate_funding_feed_cache() -> None:
        """Clear homepage warm keys and enqueue warm/replace."""
        FundingCacheMixin._delete_homepage_warm_keys()
        try:
            from feed.tasks import warm_funding_feed_cache

            warm_funding_feed_cache.delay()
        except Exception:
            # Beat will refill.
            logger.exception("Failed to queue funding feed cache warm")

    @staticmethod
    def _delete_homepage_warm_keys() -> None:
        from feed.views.funding_feed_view import FundingFeedViewSet

        warm_specs: list[tuple[str | None, str | None]] = [
            (None, None),
            *((ordering, None) for ordering in FUNDING_FEED_WARM_ORDERINGS),
            (None, FUNDING_FEED_WARM_COMPLETED_STATUS),
        ]
        factory = APIRequestFactory()
        view = FundingFeedViewSet()
        keys: list[str] = []
        for ordering, fundraise_status in warm_specs:
            for page in range(1, FEED_CACHE_MAX_CACHED_PAGE + 1):
                params: dict[str, str] = {
                    "page": str(page),
                    "page_size": str(FEED_CACHE_PAGE_SIZE),
                }
                if ordering:
                    params["ordering"] = ordering
                if fundraise_status:
                    params["fundraise_status"] = fundraise_status
                req = Request(factory.get("/api/funding_feed/", params))
                req.user = AnonymousUser()
                base = view.get_cache_key(req, "funding")
                keys.extend(base + segment for segment in FUNDING_FEED_WARM_SEGMENTS)
        if keys:
            cache.delete_many(list(dict.fromkeys(keys)))
