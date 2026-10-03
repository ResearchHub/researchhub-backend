"""Activity-feed cache helpers.

Warm/replace model: Celery refreshes pages 1-N every 5 minutes via ``cache.set``.
No delete-based invalidation.
"""

from __future__ import annotations

from rest_framework.request import Request

from feed.cache_segment import (
    FEED_CACHE_PAGE_SIZE,
    is_cache_disabled,
    is_cacheable_page,
)

# Bump when unscoped public feed filtering or serialization changes.
ACTIVITY_FEED_CACHE_VERSION = 3


def activity_feed_cache_key(page: int, page_size: int = FEED_CACHE_PAGE_SIZE) -> str:
    return (
        f"activity_feed:public:v{ACTIVITY_FEED_CACHE_VERSION}:"
        f"page-{page}:size-{page_size}"
    )


def should_cache_activity_feed(request: Request) -> bool:
    """Return whether this request may use the shared public activity-feed cache."""
    if is_cache_disabled(request):
        return False

    params = request.query_params
    if (
        params.get("scope")
        or params.get("grant_id")
        or params.get("document_type")
        or params.get("content_type")
        or params.getlist("comment_type")
        or params.get("include_hot_score_breakdown", "").lower() == "true"
    ):
        return False

    return is_cacheable_page(request)
