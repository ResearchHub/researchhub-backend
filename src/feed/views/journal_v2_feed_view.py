"""
Post-based journal feed for funded proposal journeys.

This feed renders one card per journal journey. The card is the registered
report when a journey has one, otherwise it is the funded proposal.
"""

from django.db.models import (
    Count,
    F,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
)
from django.db.models.functions import Coalesce
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from feed.feed_list_dto import (
    FundingFeedListEntrySerializer,
    serialize_fund_feed_metrics,
)
from feed.views.feed_view_mixin import FeedViewMixin
from purchase.models import Grant, GrantApplication
from purchase.related_models.grant_application_model import approved_proposal_filters
from reputation.related_models.bounty import Bounty
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from review.models import Review

from .common import FeedPagination


class JournalV2FeedViewSet(FeedViewMixin, ModelViewSet):
    """ViewSet for the post-based ResearchHub journal feed."""

    serializer_class = FundingFeedListEntrySerializer
    permission_classes = []
    pagination_class = FeedPagination

    def get_serializer_context(self) -> dict:
        """Return serializer context shared with other feed viewsets."""
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    def list(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Return journal journey feed entries built from latest stage posts."""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        feed_entries = []
        for post in page:
            feed_entry = self.build_unsaved_feed_entry(
                post, self._post_content_type, post.created_by
            )
            feed_entry.metrics = serialize_fund_feed_metrics(
                post, self._post_content_type
            )
            feed_entries.append(feed_entry)

        serializer = self.get_serializer(feed_entries, many=True)
        response_data = self.get_paginated_response(serializer.data).data

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response_data)

        return Response(response_data)

    def get_queryset(self) -> QuerySet[ResearchhubPost]:
        """Return one public latest-stage post for each journal journey."""
        registered_report_id = self._build_stage_id_subquery(REGISTERED_REPORT)
        proposal_id = self._build_stage_id_subquery(PREREGISTRATION)

        return (
            self._build_base_queryset()
            .annotate(
                latest_stage_id=Coalesce(
                    registered_report_id,
                    proposal_id,
                    output_field=IntegerField(),
                )
            )
            .filter(id=F("latest_stage_id"))
            .order_by("-created_date", "-id")
        )

    @staticmethod
    def _build_stage_id_subquery(document_type: str) -> Subquery:
        """Build a post-id subquery for one stage in the outer post's journey."""
        stage_ids = (
            ResearchhubPost.objects.filter(
                journey_id=OuterRef("journey_id"),
                document_type=document_type,
            )
            .order_by("id")
            .values("id")[:1]
        )
        return Subquery(stage_ids, output_field=IntegerField())

    @staticmethod
    def _build_base_queryset() -> QuerySet[ResearchhubPost]:
        """Build the visible journal-stage post queryset with card prefetches."""
        application_lookup = "applications"
        annotated_grants = Grant.objects.annotate(
            num_applicants=Count(
                application_lookup,
                distinct=True,
                filter=Q(**approved_proposal_filters(application_lookup)),
            )
        ).prefetch_related("unified_document__posts")

        grant_applications_prefetch = Prefetch(
            "grant_applications",
            queryset=GrantApplication.objects.prefetch_related(
                Prefetch("grant", queryset=annotated_grants)
            ),
        )

        return (
            ResearchhubPost.objects.select_related(
                "created_by",
                "created_by__author_profile",
                "journey",
                "unified_document",
            )
            .prefetch_related(
                "authors",
                "unified_document__hubs",
                "unified_document__fundraises",
                "unified_document__fundraises__nonprofit_links__nonprofit",
                Prefetch(
                    "unified_document__reviews",
                    queryset=Review.objects.filter(is_removed=False).select_related(
                        "created_by__author_profile"
                    ),
                ),
                Prefetch(
                    "unified_document__related_bounties",
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
                grant_applications_prefetch,
            )
            .filter(
                document_type__in=[PREREGISTRATION, REGISTERED_REPORT],
                journey__is_in_journal=True,
                journey_id__isnull=False,
            )
            .publicly_visible()
        )
