from typing import Any, NamedTuple

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, QuerySet
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from feed.models import FeedEntry
from feed.serializers import ModeratorFeedEntrySerializer
from feed.views.common import FeedPagination as BaseFeedPagination
from feed.views.feed_view_mixin import FeedViewMixin
from paper.related_models.paper_model import Paper
from purchase.models import Grant
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.permissions import IsModerator
from user.related_models.risk_score_model import RiskScore


class PendingSource(NamedTuple):
    queryset: QuerySet
    content_type: ContentType
    author_attr: str


class ModeratorFeedPagination(BaseFeedPagination):
    page_size = 30


class ModeratorFeedViewSet(FeedViewMixin, GenericViewSet):
    """Moderator-only feeds: the moderation queue and its per-type counts.

    Kept separate from the public ``FeedViewSet`` so moderator concerns never
    complicate the public feed. Access is enforced once at the class level.
    """

    queryset = FeedEntry.objects.none()
    serializer_class = ModeratorFeedEntrySerializer
    permission_classes = [IsModerator]
    pagination_class = ModeratorFeedPagination

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    @action(detail=False, methods=["get"], url_path="pending_moderation")
    def pending_moderation(self, request: Request) -> Response:
        """Serve works awaiting moderation, rendered in the standard feed shape.

        Pending works have no persisted FeedEntry (publication is deferred until
        approval), so feed entries are built on the fly from the source models --
        the same approach the journal feed uses.
        """
        content_type = (request.query_params.get("content_type") or "").upper()
        source = self._pending_moderation_source(content_type)
        if source is None:
            return Response(
                {"message": "Unsupported content_type."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        page = self.paginate_queryset(source.queryset)
        authors = [getattr(item, source.author_attr) for item in page]
        feed_entries = [
            self.build_unsaved_feed_entry(item, source.content_type, author)
            for item, author in zip(page, authors)
        ]
        context = {
            **self.get_serializer_context(),
            "risk_score_by_user_id": self._risk_score_by_user_id(authors),
        }
        serializer = self.get_serializer(feed_entries, many=True, context=context)
        return self.get_paginated_response(serializer.data)

    @action(detail=False, methods=["get"], url_path="pending_moderation/counts")
    def pending_moderation_counts(self, request: Request) -> Response:
        """Return counts of works awaiting moderation, grouped by tab.

        Mirrors the pending queue querysets so tab badges match the rows the
        moderator can load. Grants gate on ``Grant.status``.
        """
        post_counts = dict(
            self._pending_posts_queryset(
                document_type__in=[PREREGISTRATION, DISCUSSION]
            )
            .values_list("document_type")
            .annotate(total=Count("id"))
        )
        return Response(
            {
                "funding_opportunities": Grant.objects.filter(
                    status=Grant.PENDING
                ).count(),
                "proposals": post_counts.get(PREREGISTRATION, 0),
                "posts": post_counts.get(DISCUSSION, 0),
                "journal_entries": self._pending_papers_queryset().count(),
            }
        )

    @staticmethod
    def _risk_score_by_user_id(authors: list[Any]) -> dict[int, int]:
        """Batch-load risk scores for the page's authors in a single query."""
        user_ids = {author.id for author in authors if author}
        return dict(
            RiskScore.objects.filter(user_id__in=user_ids).values_list(
                "user_id", "score"
            )
        )

    def _pending_moderation_source(self, content_type: str) -> PendingSource | None:
        """Map a moderation tab's content_type to its pending queryset."""
        if content_type == "PAPER":
            # Every author-submitted paper (preprint or journal) is gated at
            # submission, so the queue is simply the pending ones. Machine
            # imports (e.g. OpenAlex) default to APPROVED and never appear here.
            queryset = (
                self._pending_papers_queryset()
                .select_related(
                    "uploaded_by",
                    "uploaded_by__author_profile",
                    "unified_document",
                    "version",
                )
                .prefetch_related("unified_document__hubs")
                .order_by("-created_date")
            )
            return PendingSource(queryset, self._paper_content_type, "uploaded_by")

        post_document_type = {
            "PREREGISTRATION": PREREGISTRATION,
            "POST": DISCUSSION,
        }.get(content_type)
        if post_document_type is None:
            return None

        queryset = (
            self._pending_posts_queryset(document_type=post_document_type)
            .select_related(
                "created_by", "created_by__author_profile", "unified_document"
            )
            .prefetch_related("unified_document__hubs")
            .order_by("-created_date")
        )
        return PendingSource(queryset, self._post_content_type, "created_by")

    @staticmethod
    def _pending_papers_queryset() -> QuerySet:
        return Paper.objects.filter(
            unified_document__status=ResearchhubUnifiedDocument.PENDING,
            is_removed=False,
        )

    @staticmethod
    def _pending_posts_queryset(**filters: Any) -> QuerySet:
        return ResearchhubPost.objects.filter(
            unified_document__status=ResearchhubUnifiedDocument.PENDING,
            **filters,
        )
