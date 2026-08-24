"""Activity-feed cache helpers.

Warm/replace model: Celery refreshes pages 1-20 every 5 minutes via ``cache.set``.
No delete-based invalidation.
"""

from __future__ import annotations

from rest_framework.request import Request

ACTIVITY_FEED_CACHE_PAGE_SIZE = 20
ACTIVITY_FEED_MAX_CACHED_PAGE = 20
ACTIVITY_FEED_CACHE_TIMEOUT = 60 * 10
# Bump when unscoped public feed filtering or serialization changes.
ACTIVITY_FEED_CACHE_VERSION = 3


def activity_feed_cache_key(
    page: int, page_size: int = ACTIVITY_FEED_CACHE_PAGE_SIZE
) -> str:
    """Return the cache key for an unscoped public activity-feed page."""
    return (
        f"activity_feed:public:v{ACTIVITY_FEED_CACHE_VERSION}:"
        f"page-{page}:size-{page_size}"
    )


def should_cache_activity_feed(request: Request) -> bool:
    """Return whether this request may use the shared public activity-feed cache."""
    user = request.user
    if user.is_authenticated and user.is_moderator_or_editor():
        return False

    params = request.query_params
    if (
        params.get("scope")
        or params.get("grant_id")
        or params.get("document_type")
        or params.get("content_type")
        or params.get("comment_type")
    ):
        return False

    try:
        page = int(params.get("page", "1"))
        page_size = int(params.get("page_size", str(ACTIVITY_FEED_CACHE_PAGE_SIZE)))
    except (TypeError, ValueError):
        return False

    return (
        page_size == ACTIVITY_FEED_CACHE_PAGE_SIZE
        and 1 <= page <= ACTIVITY_FEED_MAX_CACHED_PAGE
    )
