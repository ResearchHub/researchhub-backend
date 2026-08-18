from collections.abc import Callable

from django.db import transaction
from django.db.models import Prefetch, QuerySet

from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.document_filter_model import DocumentFilter
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User

# Dashboard list is grants, posts, and proposals for now — not papers/preprints.
_EXCLUDED_LIST_DOCUMENT_TYPES = (DISCUSSION, GRANT, PREREGISTRATION)


class UnifiedDocumentFeedVisibilityService:
    """Toggle whether a unified document appears in public feeds.

    Hiding is feed-only: detail pages and other direct access are unchanged,
    and persisted feed entries are left in place so unhiding restores
    visibility without rebuilding feed data.

    Other public feeds keep serving cached pages until TTL. The unscoped
    activity feed is the exception: its 20 cached pages are replaced so a
    hide/unhide is visible immediately.
    """

    def __init__(
        self,
        activity_feed_cache_warmer: Callable[[], None] | None = None,
    ) -> None:
        self.activity_feed_cache_warmer = (
            activity_feed_cache_warmer or self._warm_activity_feed_cache
        )

    def exclude_from_feed(
        self, unified_document_id: int, user: User
    ) -> ResearchhubUnifiedDocument:
        """Hide a document from public feeds. Idempotent."""
        return self._set_excluded(unified_document_id, user, excluded=True)

    def include_in_feed(
        self, unified_document_id: int, user: User
    ) -> ResearchhubUnifiedDocument:
        """Restore a document to public feeds. Idempotent."""
        return self._set_excluded(unified_document_id, user, excluded=False)

    def list_excluded_from_feed(self, query: str | None = None) -> QuerySet:
        """Currently hidden documents, newest first."""
        queryset = (
            ResearchhubUnifiedDocument.objects.filter(
                document_filter__is_excluded_in_feed=True,
                document_type__in=_EXCLUDED_LIST_DOCUMENT_TYPES,
            )
            .select_related("document_filter")
            .prefetch_related(
                Prefetch(
                    "posts",
                    queryset=ResearchhubPost.objects.select_related(
                        "created_by",
                        "created_by__author_profile",
                    ).prefetch_related("authors"),
                ),
                "grants",
                "fundraises",
            )
            .order_by("-id")
        )
        term = (query or "").strip()
        if term:
            queryset = queryset.filter(posts__title__icontains=term).distinct()
        return queryset

    def _set_excluded(
        self, unified_document_id: int, user: User, excluded: bool
    ) -> ResearchhubUnifiedDocument:
        self._assert_moderator(user)
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
            self.activity_feed_cache_warmer()
        return unified_document

    @staticmethod
    def _warm_activity_feed_cache() -> None:
        from feed.views.activity_feed_view import ActivityFeedViewSet

        ActivityFeedViewSet.warm_public_cache()

    @staticmethod
    def _assert_moderator(user: User) -> None:
        if (
            user is None
            or not getattr(user, "is_authenticated", False)
            or not user.moderator
        ):
            raise PermissionError("Need to be a moderator.")
