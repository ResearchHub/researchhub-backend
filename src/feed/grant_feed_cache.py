"""Grant-feed cache helpers.

Segment / disable_cache / TTL / page windows live in ``feed.cache_segment``.
Grant discovery supports private segments. ``created_by`` remains uncached.
"""

from __future__ import annotations

from rest_framework.request import Request

from feed.cache_segment import (
    FEED_CACHE_SEGMENT_ADMIN,
    FEED_CACHE_SEGMENT_PUBLIC,
    is_cache_disabled,
    is_cacheable_page,
)

GRANT_FEED_WARM_ORDERINGS = ("most_applicants", "newest", "amount_raised")
GRANT_FEED_WARM_SEGMENTS = (FEED_CACHE_SEGMENT_PUBLIC, FEED_CACHE_SEGMENT_ADMIN)

GRANT_FEED_INVALIDATION_ORDERINGS = [
    "latest",
    "newest",
    "upvotes",
    "most_applicants",
    "amount_raised",
]
GRANT_FEED_INVALIDATION_STATUSES = ["", "OPEN", "CLOSED", "COMPLETED"]


def should_cache_grant_feed(request: Request) -> bool:
    """Return whether this request may use the shared public grant-feed cache."""
    if is_cache_disabled(request):
        return False
    if request.query_params.get("organization"):
        return False
    return is_cacheable_page(request)
