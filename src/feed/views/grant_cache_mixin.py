import logging

from django.db import transaction

from feed.grant_feed_cache import get_grant_feed_cache_version
from feed.views.funding_cache_mixin import FundingCacheMixin
from purchase.models import GrantApplication

logger = logging.getLogger(__name__)


class GrantCacheMixin:
    def get_cache_key(self, request, feed_type=""):
        base_key = super().get_cache_key(request, feed_type)
        status = request.query_params.get("status", "")
        created_by = request.query_params.get("created_by", "")
        include_key_insights = request.query_params.get("include_key_insights", "")
        version = get_grant_feed_cache_version()
        return f"{base_key}:{status}:{created_by}:{include_key_insights}:v{version}"

    @staticmethod
    def invalidate_grant_feed_cache():
        """Queue invalidation and a warm after the surrounding transaction commits."""

        def _enqueue():
            try:
                from feed.tasks import invalidate_grant_feed_cache

                invalidate_grant_feed_cache.delay()
            except Exception:
                # Entries still expire after FEED_CACHE_TIMEOUT; beat refills.
                logger.exception("Failed to queue grant feed cache invalidation")

        transaction.on_commit(_enqueue)

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
