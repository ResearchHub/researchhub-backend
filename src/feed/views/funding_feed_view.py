"""
Specialized feed view focused on funding-related content for ResearchHub.
This view uses the Feed serializer on preregistration posts, instantiating
feed entries for each post instead of querying the feed table.
This is done for three reasons:
1. To provide a consistent endpoint for feed content.
2. Avoid filtering on feed entries which can be expensive since it is a large table.
3. Older feed entries are not in the feed table.
"""

from django.core.cache import cache
from django.db.models import Count, Prefetch, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from feed.cache_segment import get_feed_cache_segment
from feed.feed_list_dto import (
    FundingFeedListEntrySerializer,
    serialize_fund_feed_metrics,
)
from feed.filters import FundOrderingFilter
from feed.views.feed_view_mixin import FeedViewMixin
from feed.views.funding_cache_mixin import (
    FUNDING_FEED_MAX_CACHED_PAGE,
    FundingCacheMixin,
)
from purchase.models import Grant, GrantApplication
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.grant_application_model import approved_proposal_filters
from reputation.related_models.bounty import Bounty
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from review.models import Review

from .common import FeedPagination


class FundingFeedViewSet(FundingCacheMixin, FeedViewMixin, ModelViewSet):
    serializer_class = FundingFeedListEntrySerializer
    permission_classes = []
    pagination_class = FeedPagination
    filter_backends = [DjangoFilterBackend, FundOrderingFilter]
    ordering_fields = ["newest", "best", "upvotes", "most_applicants", "amount_raised"]
    ordering = "best"  # Default ordering

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    def list(self, request, *args, **kwargs):
        page = request.query_params.get("page", "1")
        page_num = int(page)
        grant_id = request.query_params.get("grant_id", None)
        created_by = request.query_params.get("created_by", None)
        funded_by = request.query_params.get("funded_by", None)
        suffix, should_cache = get_feed_cache_segment(request)
        use_cache = (
            should_cache
            and page_num <= FUNDING_FEED_MAX_CACHED_PAGE
            and grant_id is None
            and created_by is None
            and funded_by is None
        )
        cache_key = (
            (self.get_cache_key(request, "funding") + suffix) if use_cache else None
        )

        if cache_key:
            cached_response = cache.get(cache_key)
            if cached_response:
                if request.user.is_authenticated:
                    self.add_user_votes_to_response(request.user, cached_response)
                return Response(cached_response)

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

        serializer = FundingFeedListEntrySerializer(
            feed_entries, many=True, context=self.get_serializer_context()
        )
        response_data = self.get_paginated_response(serializer.data).data

        if cache_key:
            cache.set(cache_key, response_data, timeout=self.DEFAULT_CACHE_TIMEOUT)

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response_data)

        return Response(response_data)

    def get_queryset(self):
        fundraise_status = self.request.query_params.get("fundraise_status")
        grant_id = self.request.query_params.get("grant_id")
        created_by = self.request.query_params.get("created_by")
        funded_by = self.request.query_params.get("funded_by")

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

        queryset = (
            ResearchhubPost.objects.select_related(
                "created_by",
                "created_by__author_profile",
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
                document_type=PREREGISTRATION,
                unified_document__is_removed=False,
                unified_document__status=ResearchhubUnifiedDocument.APPROVED,
            )
        )

        # Personalized feeds (grant_id / created_by / funded_by) are never
        # cached -- see `use_cache` in list() -- so they can safely respect
        # per-viewer visibility. This lets the author, grant owners, invited
        # reviewers, and moderators see private preregistrations and grants
        # (e.g. on the author profile's Proposals tab) while everyone else,
        # including anonymous viewers, still only sees public ones.
        if grant_id or created_by or funded_by:
            visible_ids = ResearchhubPost.objects.visible_to(self.request.user).values(
                "id"
            )
            queryset = queryset.filter(id__in=visible_ids)
        else:
            # The public discovery feed stays user-agnostic so it can be cached
            # for everyone; never expose private or unmoderated work here.
            queryset = queryset.publicly_visible()

        if created_by:
            queryset = queryset.filter(created_by_id=created_by)

        if funded_by:
            queryset = queryset.filter(
                grant_applications__grant__unified_document__posts__created_by_id=funded_by
            ).distinct()

        if grant_id:
            queryset = queryset.filter(grant_applications__grant_id=grant_id)

        if fundraise_status:
            status_upper = fundraise_status.upper()
            if status_upper == "OPEN":
                queryset = queryset.filter(
                    unified_document__fundraises__status=Fundraise.OPEN
                )
            elif status_upper == "CLOSED":
                queryset = queryset.filter(
                    unified_document__fundraises__status=Fundraise.COMPLETED
                )

        return queryset
