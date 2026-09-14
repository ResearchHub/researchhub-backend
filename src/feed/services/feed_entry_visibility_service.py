import logging
from collections.abc import Callable

from django.db import transaction
from django.db.models import Count, Prefetch, Q, QuerySet

from feed.models import FeedEntry, HiddenFeedEntry
from purchase.models import Fundraise, Grant
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.models import User

logger = logging.getLogger(__name__)


class FeedEntryVisibilityService:
    """Hide or restore individual feed entries in public feeds."""

    def __init__(
        self,
        activity_feed_cache_warmer: Callable[[], None] | None = None,
    ) -> None:
        self.activity_feed_cache_warmer = (
            activity_feed_cache_warmer or self._queue_activity_feed_cache_warm
        )

    def exclude_from_feed(self, feed_entry_id: int, hidden_by: User) -> FeedEntry:
        """Hide one feed entry from public feeds. Idempotent."""
        return self._set_hidden(feed_entry_id, hidden_by=hidden_by, hidden=True)

    def include_in_feed(self, feed_entry_id: int) -> FeedEntry:
        """Restore one feed entry to public feeds. Idempotent."""
        return self._set_hidden(feed_entry_id, hidden_by=None, hidden=False)

    def list_excluded_from_feed(self, query: str | None = None) -> QuerySet:
        """Feed entries currently hidden from public feeds, newest first."""
        queryset = (
            FeedEntry.objects.filter(feed_hide__isnull=False)
            .select_related(
                "content_type",
                "unified_document",
                "user",
                "user__author_profile",
                "user__userverification",
                "unified_document__paper__uploaded_by__author_profile",
                "feed_hide",
                "feed_hide__hidden_by",
            )
            .prefetch_related(
                Prefetch(
                    "unified_document__posts",
                    queryset=ResearchhubPost.objects.select_related(
                        "created_by__author_profile"
                    ).prefetch_related("author_links"),
                ),
                Prefetch(
                    "unified_document__grants",
                    queryset=Grant.objects.annotate(
                        num_applicants=Count("applications", distinct=True),
                    ),
                ),
                Prefetch(
                    "unified_document__fundraises",
                    queryset=Fundraise.objects.select_related(
                        "created_by__author_profile",
                        "escrow",
                    ).prefetch_related("nonprofit_links__nonprofit"),
                ),
                "unified_document__paper__authors",
            )
            .order_by("-feed_hide__created_date")
        )
        term = (query or "").strip()
        if term:
            queryset = queryset.filter(
                Q(unified_document__posts__title__icontains=term)
                | Q(unified_document__paper__title__icontains=term)
                | Q(unified_document__paper__paper_title__icontains=term)
            ).distinct()
        return queryset

    def _set_hidden(
        self,
        feed_entry_id: int,
        hidden_by: User | None,
        hidden: bool,
    ) -> FeedEntry:
        changed = False

        with transaction.atomic():
            feed_entry = FeedEntry.objects.select_for_update(of=("self",)).get(
                pk=feed_entry_id
            )
            if hidden:
                _, created = HiddenFeedEntry.objects.get_or_create(
                    feed_entry=feed_entry,
                    defaults={"hidden_by": hidden_by},
                )
                changed = created
            else:
                deleted_count, _ = HiddenFeedEntry.objects.filter(
                    feed_entry=feed_entry
                ).delete()
                changed = deleted_count > 0

            if changed:
                transaction.on_commit(self.activity_feed_cache_warmer, robust=True)

        return feed_entry

    @staticmethod
    def _queue_activity_feed_cache_warm() -> None:
        from feed.tasks import warm_activity_feed_cache

        try:
            warm_activity_feed_cache.delay()
        except Exception:
            logger.exception("Failed to enqueue activity feed cache warm")
