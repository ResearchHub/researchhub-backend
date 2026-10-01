import logging

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db import transaction
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from feed.cache_segment import FEED_CACHE_MAX_CACHED_PAGE, FEED_CACHE_PAGE_SIZE
from feed.grant_feed_cache import (
    GRANT_FEED_INVALIDATION_ORDERINGS,
    GRANT_FEED_INVALIDATION_STATUSES,
    GRANT_FEED_WARM_ORDERINGS,
    GRANT_FEED_WARM_SEGMENTS,
)
from feed.views.funding_cache_mixin import FundingCacheMixin
from purchase.models import GrantApplication
from researchhub_document.related_models.constants.document_type import GRANT
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

logger = logging.getLogger(__name__)


class GrantCacheMixin:
    def get_cache_key(self, request, feed_type=""):
        base_key = super().get_cache_key(request, feed_type)
        status = request.query_params.get("status", "")
        created_by = request.query_params.get("created_by", "")
        include_key_insights = request.query_params.get("include_key_insights", "")
        return f"{base_key}:{status}:{created_by}:{include_key_insights}"

    @staticmethod
    def invalidate_grant_feed_cache():
        """Clear keys and enqueue warm after the surrounding transaction commits."""

        def _invalidate():
            GrantCacheMixin._delete_created_by_cache_keys()
            GrantCacheMixin._delete_homepage_warm_keys()
            try:
                from feed.tasks import warm_grant_feed_cache

                warm_grant_feed_cache.delay()
            except Exception:
                # Beat will refill.
                logger.exception("Failed to queue grant feed cache warm")

        transaction.on_commit(_invalidate)

    @staticmethod
    def _delete_created_by_cache_keys() -> None:
        page_size = FEED_CACHE_PAGE_SIZE
        creator_ids = (
            ResearchhubPost.objects.filter(document_type=GRANT)
            .values_list("created_by_id", flat=True)
            .distinct()
        )
        created_by_values = [""] + [str(cid) for cid in creator_ids if cid is not None]

        for ordering in GRANT_FEED_INVALIDATION_ORDERINGS:
            sort_part = f"-{ordering}" if ordering != "latest" else ""
            for status in GRANT_FEED_INVALIDATION_STATUSES:
                for created_by in created_by_values:
                    for include_key_insights in ("", "true"):
                        for page in range(1, FEED_CACHE_MAX_CACHED_PAGE + 1):
                            cache_key = (
                                f"grants_feed:popular:all:all:none:"
                                f"{page}-{page_size}{sort_part}:{status}:"
                                f"{created_by}:{include_key_insights}"
                            )
                            cache.delete(cache_key + ":public")
                            cache.delete(cache_key + ":admin")

    @staticmethod
    def _delete_homepage_warm_keys() -> None:
        from feed.views.grant_feed_view import GrantFeedViewSet

        warm_orderings: tuple[str | None, ...] = (None, *GRANT_FEED_WARM_ORDERINGS)
        factory = APIRequestFactory()
        view = GrantFeedViewSet()
        keys: list[str] = []
        for ordering in warm_orderings:
            for page in range(1, FEED_CACHE_MAX_CACHED_PAGE + 1):
                params: dict[str, str] = {
                    "page": str(page),
                    "page_size": str(FEED_CACHE_PAGE_SIZE),
                }
                if ordering:
                    params["ordering"] = ordering
                req = Request(factory.get("/api/grant_feed/", params))
                req.user = AnonymousUser()
                base = view.get_cache_key(req, "grants")
                keys.extend(base + segment for segment in GRANT_FEED_WARM_SEGMENTS)
        if keys:
            cache.delete_many(list(dict.fromkeys(keys)))

    @staticmethod
    def invalidate_if_grant_linked(unified_document):
        if unified_document is None:
            return
        if (
            unified_document.grants.exists()
            or GrantApplication.objects.filter(
                preregistration_post__unified_document=unified_document
            ).exists()
        ):
            GrantCacheMixin.invalidate_grant_feed_cache()
            FundingCacheMixin.invalidate_funding_feed_cache()
