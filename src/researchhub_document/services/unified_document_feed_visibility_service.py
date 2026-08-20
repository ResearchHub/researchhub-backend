import logging
from collections.abc import Callable

from django.db import transaction

from researchhub_document.related_models.document_filter_model import DocumentFilter
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)

logger = logging.getLogger(__name__)


class UnifiedDocumentFeedVisibilityService:
    """Toggle whether a unified document appears in public feeds.

    Hiding is feed-only: detail pages and other direct access are unchanged,
    and persisted feed entries are left in place so unhiding restores
    visibility without rebuilding feed data.
    """

    def __init__(
        self,
        activity_feed_cache_warmer: Callable[[], None] | None = None,
    ) -> None:
        self.activity_feed_cache_warmer = (
            activity_feed_cache_warmer or self._queue_activity_feed_cache_warm
        )

    def exclude_from_feed(self, unified_document_id: int) -> ResearchhubUnifiedDocument:
        """Hide a document from public feeds. Idempotent."""
        return self._set_excluded(unified_document_id, excluded=True)

    def include_in_feed(self, unified_document_id: int) -> ResearchhubUnifiedDocument:
        """Restore a document to public feeds. Idempotent."""
        return self._set_excluded(unified_document_id, excluded=False)

    def _set_excluded(
        self, unified_document_id: int, excluded: bool
    ) -> ResearchhubUnifiedDocument:
        changed = False

        with transaction.atomic():
            unified_document = (
                ResearchhubUnifiedDocument.objects.select_for_update(of=("self",))
                .select_related("document_filter")
                .get(pk=unified_document_id)
            )
            document_filter = unified_document.document_filter
            if document_filter is None:
                document_filter = DocumentFilter.objects.create(
                    is_excluded_in_feed=excluded
                )
                unified_document.document_filter = document_filter
                unified_document.save(update_fields=["document_filter"])
                changed = True
            elif document_filter.is_excluded_in_feed != excluded:
                document_filter.is_excluded_in_feed = excluded
                document_filter.save(update_fields=["is_excluded_in_feed"])
                changed = True

            if changed:
                transaction.on_commit(self.activity_feed_cache_warmer, robust=True)
        return unified_document

    @staticmethod
    def _queue_activity_feed_cache_warm() -> None:
        from feed.tasks import warm_activity_feed_cache

        try:
            warm_activity_feed_cache.delay()
        except Exception:
            logger.exception("Failed to enqueue activity feed cache warm")
