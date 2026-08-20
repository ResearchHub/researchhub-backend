"""
Post-based journal feed for registered reports.
"""

from typing import Any

from django.db.models import Exists, OuterRef, Prefetch
from django.db.models.query import QuerySet
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from feed.feed_list_dto import (
    FundFeedListEntrySerializer,
    JournalFeedPostSerializer,
    serialize_journal_feed_metrics,
)
from feed.feed_visibility import exclude_hidden_from_feed
from feed.filters import JournalFeedOrderingFilter
from feed.views.feed_view_mixin import FeedViewMixin
from organizations.models import NonprofitFundraiseLink
from purchase.models import Fundraise
from purchase.services.fundraise_eligibility_service import (
    filter_fundraises_with_funding,
)
from reputation.related_models.bounty import Bounty
from researchhub_document.related_models.constants.document_type import (
    REGISTERED_REPORT,
)
from researchhub_document.related_models.researchhub_post_model import (
    ResearchhubPost,
    ResearchhubPostAuthor,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from review.models import Review

from .common import FeedPagination


class JournalV2FeedViewSet(FeedViewMixin, ReadOnlyModelViewSet):
    """Feed viewset for the new ResearchHub Journal journey feed."""

    serializer_class = FundFeedListEntrySerializer
    permission_classes = []
    pagination_class = FeedPagination
    filter_backends = [DjangoFilterBackend, JournalFeedOrderingFilter]
    ordering_fields = ["newest", "best", "peer_review_score"]
    ordering = "best"

    def get_serializer_context(self) -> dict[str, Any]:
        """Return serializer context shared by feed list responses."""
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        context["include_post_ids"] = True
        context["post_serializer_class"] = JournalFeedPostSerializer
        return context

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Return paginated journal cards for registered reports."""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        feed_entries = []
        for post in page:
            feed_entry = self.build_unsaved_feed_entry(
                post, self._post_content_type, post.created_by
            )
            feed_entry.metrics = serialize_journal_feed_metrics(
                post, self._post_content_type
            )
            feed_entries.append(feed_entry)

        serializer = self.serializer_class(
            feed_entries, many=True, context=self.get_serializer_context()
        )
        response_data = self.get_paginated_response(serializer.data).data

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response_data)

        return Response(response_data)

    def get_queryset(self) -> QuerySet:
        """Return visible registered reports backed by funded proposals."""
        return self._build_journal_stage_queryset()

    def _build_journal_stage_queryset(self) -> QuerySet:
        """Build the base queryset for public journal stages."""
        funded_completed_fundraises = filter_fundraises_with_funding(
            Fundraise.objects.filter(status=Fundraise.COMPLETED)
        )
        funded_completed_source_fundraise = funded_completed_fundraises.filter(
            unified_document_id=OuterRef(
                "journey__preregistration_post__unified_document_id"
            ),
        )
        public_grant_post = ResearchhubPost.objects.publicly_visible().filter(
            pk=OuterRef("journey__grant_post_id"),
        )
        source_proposal_prefetches = [
            Prefetch(
                "journey__preregistration_post__unified_document__fundraises",
                queryset=funded_completed_fundraises.select_related(
                    "created_by",
                    "escrow",
                )
                .prefetch_related(
                    Prefetch(
                        "nonprofit_links",
                        queryset=NonprofitFundraiseLink.objects.select_related(
                            "nonprofit"
                        ),
                    )
                )
                .order_by("-created_date", "-id"),
            ),
            Prefetch(
                "journey__preregistration_post__unified_document__reviews",
                queryset=Review.objects.filter(is_removed=False).select_related(
                    "created_by__author_profile"
                ),
            ),
            Prefetch(
                "journey__preregistration_post__unified_document__related_bounties",
                queryset=Bounty.objects.filter(parent__isnull=True)
                .select_related("created_by")
                .prefetch_related(
                    Prefetch(
                        "children",
                        queryset=Bounty.objects.select_related(
                            "created_by__author_profile"
                        ),
                    )
                ),
            ),
        ]

        queryset = (
            ResearchhubPost.objects.select_related(
                "created_by",
                "created_by__author_profile",
                "journey",
                "journey__preregistration_post",
                "journey__preregistration_post__unified_document",
                "unified_document",
            )
            .prefetch_related(
                Prefetch(
                    "author_links",
                    queryset=ResearchhubPostAuthor.objects.select_related(
                        "author__user"
                    ),
                ),
                *source_proposal_prefetches,
            )
            .annotate(
                has_funded_completed_source_fundraise=Exists(
                    funded_completed_source_fundraise
                ),
                has_public_grant_post=Exists(public_grant_post),
            )
            .publicly_visible()
            .filter(
                document_type=REGISTERED_REPORT,
                has_funded_completed_source_fundraise=True,
                journey__preregistration_post__isnull=False,
                journey__preregistration_post__unified_document__is_removed=False,
                journey__preregistration_post__unified_document__status=(
                    ResearchhubUnifiedDocument.APPROVED
                ),
            )
        )
        return exclude_hidden_from_feed(queryset)
