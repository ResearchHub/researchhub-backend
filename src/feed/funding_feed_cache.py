"""Funding-feed cache helpers.

Funding discovery supports private segments. ``created_by`` / ``grant_id`` /
``funded_by`` stay uncached.
"""

from __future__ import annotations

from rest_framework.request import Request

from feed.cache_segment import (
    FEED_CACHE_SEGMENT_ADMIN,
    FEED_CACHE_SEGMENT_PUBLIC,
    is_cache_disabled,
    is_cacheable_page,
)

FUNDING_FEED_WARM_ORDERINGS = ("best", "newest", "most_applicants", "amount_raised")
FUNDING_FEED_WARM_SEGMENTS = (FEED_CACHE_SEGMENT_PUBLIC, FEED_CACHE_SEGMENT_ADMIN)
FUNDING_FEED_WARM_COMPLETED_STATUS = "CLOSED"


def should_cache_funding_feed(request: Request) -> bool:
    """Return whether this request may use the shared public funding-feed cache."""
    if is_cache_disabled(request):
        return False

    params = request.query_params
    if (
        params.get("grant_id")
        or params.get("created_by")
        or params.get("funded_by")
        or params.get("include_private", "").lower() in ("true", "1")
    ):
        return False

    return is_cacheable_page(request)
