import logging
import time

from django.core.cache import cache
from django.db import transaction

from feed.views.funding_cache_mixin import FundingCacheMixin
from purchase.models import GrantApplication

logger = logging.getLogger(__name__)

# Part of every grant feed cache key: incrementing it invalidates all cached pages
# at once, and the orphaned pages expire with FEED_CACHE_TIMEOUT. The counter is
# seeded with a timestamp, so a lost key never restarts on an old generation.
GRANT_FEED_GENERATION_KEY = "grants_feed:generation"


class GrantCacheMixin:
    def get_cache_key(self, request, feed_type=""):
        base_key = super().get_cache_key(request, feed_type)
        status = request.query_params.get("status", "")
        created_by = request.query_params.get("created_by", "")
        include_key_insights = request.query_params.get("include_key_insights", "")
        generation = cache.get_or_set(
            GRANT_FEED_GENERATION_KEY, time.time_ns, timeout=None
        )
        return f"{base_key}:{status}:{created_by}:{include_key_insights}:{generation}"

    @staticmethod
    def invalidate_grant_feed_cache():
        """Start a new key generation and enqueue warm after the transaction commits."""

        def _invalidate():
            cache.add(GRANT_FEED_GENERATION_KEY, time.time_ns(), timeout=None)
            cache.incr(GRANT_FEED_GENERATION_KEY)
            try:
                from feed.tasks import warm_grant_feed_cache

                warm_grant_feed_cache.delay()
            except Exception:
                # Beat will refill.
                logger.exception("Failed to queue grant feed cache warm")

        transaction.on_commit(_invalidate)

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
