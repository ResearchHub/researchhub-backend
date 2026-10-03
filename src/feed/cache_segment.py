"""Shared feed-cache policy for Activity, Grant, and Funding discovery feeds."""

from __future__ import annotations

from rest_framework.request import Request

from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

FEED_CACHE_PAGE_SIZE = 20
FEED_CACHE_TIMEOUT = 60 * 10
FEED_CACHE_MAX_CACHED_PAGE = 20

FEED_CACHE_SEGMENT_PUBLIC = ":public"
FEED_CACHE_SEGMENT_ADMIN = ":admin"


def is_cache_disabled(request: Request) -> bool:
    """True when a mod/editor passed ``?disable_cache=true|1``."""
    disable = request.query_params.get("disable_cache", "").lower()
    if disable not in ("true", "1"):
        return False
    user = getattr(request, "user", None)
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and user.is_moderator_or_editor()
    )


def is_cacheable_page(request: Request) -> bool:
    """True when page/page_size fall in the shared warmable window."""
    try:
        page = int(request.query_params.get("page", "1"))
        size = int(request.query_params.get("page_size", str(FEED_CACHE_PAGE_SIZE)))
    except (TypeError, ValueError):
        return False
    return size == FEED_CACHE_PAGE_SIZE and 1 <= page <= FEED_CACHE_MAX_CACHED_PAGE


def get_feed_cache_segment(request: Request, *, supports_private: bool = True) -> str:
    """Return the cache segment suffix for this request.

    ``:public`` | ``:admin`` | ``:viewer-{user_id}``

    When ``supports_private`` is False (Activity discovery), always ``:public``.
    Grant/Funding pass ``supports_private=True`` so entitled users get private
    discovery payloads under distinct keys.

    Cross-feed note: the private-visibility probe is any post via
    ``visible_to(user)``, not feed-scoped. That keeps Grant owners who only
    see private nested applications on the correct ``:viewer-*`` bucket.
    """
    if not supports_private:
        return FEED_CACHE_SEGMENT_PUBLIC

    user = request.user

    if not user.is_authenticated:
        return FEED_CACHE_SEGMENT_PUBLIC

    if user.is_moderator_or_editor():
        return FEED_CACHE_SEGMENT_ADMIN

    has_private_visibility = (
        ResearchhubPost.objects.visible_to(user)
        .filter(
            unified_document__is_public=False,
            unified_document__is_removed=False,
        )
        .exists()
    )

    if has_private_visibility:
        return f":viewer-{user.id}"

    return FEED_CACHE_SEGMENT_PUBLIC


def apply_visibility_for_segment(queryset, request: Request, segment: str):
    """Restrict queryset to match segment."""
    if segment == FEED_CACHE_SEGMENT_PUBLIC:
        return queryset.publicly_visible()
    if segment == FEED_CACHE_SEGMENT_ADMIN:
        # Mods/editors: visible_to is unrestricted.
        return queryset.visible_to(request.user)
    return queryset.visible_to(request.user)
