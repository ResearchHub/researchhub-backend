"""Grant-feed cache helpers.

Segment / disable_cache / TTL / page windows live in ``feed.cache_segment``.
Grant discovery supports private segments. Keys carry a version so that one
write invalidates every entry, including ``created_by`` and viewer pages.
"""

from __future__ import annotations

import uuid

from django.core.cache import cache
from rest_framework.request import Request

from feed.cache_segment import (
    FEED_CACHE_SEGMENT_ADMIN,
    FEED_CACHE_SEGMENT_PUBLIC,
    is_cache_disabled,
    is_cacheable_page,
)

GRANT_FEED_WARM_ORDERINGS = ("most_applicants", "newest", "amount_raised")
GRANT_FEED_WARM_SEGMENTS = (FEED_CACHE_SEGMENT_PUBLIC, FEED_CACHE_SEGMENT_ADMIN)

GRANT_FEED_CACHE_VERSION_KEY = "grants_feed:version"


def get_grant_feed_cache_version() -> str:
    """Return the version every grant-feed cache key is namespaced under."""
    return cache.get(GRANT_FEED_CACHE_VERSION_KEY) or "0"


def bump_grant_feed_cache_version() -> None:
    """Invalidate every grant-feed cache entry with a single write.

    Entries under the previous version are never read again and expire after
    ``FEED_CACHE_TIMEOUT``.
    """
    cache.set(GRANT_FEED_CACHE_VERSION_KEY, uuid.uuid4().hex, timeout=None)


def should_cache_grant_feed(request: Request) -> bool:
    """Return whether this request may use the shared public grant-feed cache."""
    if is_cache_disabled(request):
        return False
    if request.query_params.get("organization"):
        return False
    return is_cacheable_page(request)
