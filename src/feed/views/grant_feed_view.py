"""
Specialized feed view focused on grant-related content for ResearchHub.
This view displays grants in a feed format, showing funding opportunities
and research grant postings.
"""

from django.core.cache import cache
from django.db.models import Prefetch, Q
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from ai_peer_review.models import ProposalReview
from feed.cache_segment import get_feed_cache_segment
from feed.feed_list_dto import GrantFeedListEntrySerializer
from feed.filters import FundOrderingFilter
from feed.views.feed_view_mixin import FeedViewMixin
from feed.views.grant_cache_mixin import GRANT_FEED_MAX_CACHED_PAGE, GrantCacheMixin
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.grant_model import Grant
from researchhub_document.related_models.constants.document_type import GRANT
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from review.models import Review

from .common import FeedPagination


class GrantFeedViewSet(GrantCacheMixin, FeedViewMixin, ModelViewSet):
    serializer_class = GrantFeedListEntrySerializer
    permission_classes = []
    pagination_class = FeedPagination
    filter_backends = [DjangoFilterBackend, FundOrderingFilter]
    is_grant_view = True
    DEFAULT_CACHE_TIMEOUT = 60 * 60 * 12
    ordering_fields = ["newest", "upvotes", "most_applicants", "amount_raised"]
    ordering = "newest"  # Default ordering

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        context["include_key_insights"] = self._include_key_insights()
        return context

    @staticmethod
    def _include_key_insights_from_request(request):
        return bool(request.query_params.get("created_by")) or (
            request.query_params.get("include_key_insights", "").lower() == "true"
        )

    def _include_key_insights(self):
        return self._include_key_insights_from_request(self.request)

    def list(self, request, *args, **kwargs):
        page = request.query_params.get("page", "1")
        page_num = int(page)
        suffix, should_cache = get_feed_cache_segment(request)
        use_cache = should_cache and page_num <= GRANT_FEED_MAX_CACHED_PAGE
        cache_key = (
            (self.get_cache_key(request, "grants") + suffix) if use_cache else None
        )

        if cache_key:
            cached_response = cache.get(cache_key)
            if cached_response:
                return Response(cached_response)

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        feed_entries = [
            self.build_unsaved_feed_entry(
                post, self._post_content_type, post.created_by
            )
            for post in page
        ]

        serializer = GrantFeedListEntrySerializer(
            feed_entries, many=True, context=self.get_serializer_context()
        )
        response_data = self.get_paginated_response(serializer.data).data

        if cache_key:
            cache.set(cache_key, response_data, timeout=self.DEFAULT_CACHE_TIMEOUT)

        return Response(response_data)

    def get_queryset(self):
        status = self.request.query_params.get("status")
        organization = self.request.query_params.get("organization")
        created_by = self.request.query_params.get("created_by")
        include_key_insights = self._include_key_insights()

        prefetch_related = [
            "unified_document__hubs",
            "unified_document__grants__applications__applicant__author_profile",
            Prefetch(
                "unified_document__grants__applications__preregistration_post__unified_document__reviews",
                queryset=Review.objects.filter(is_removed=False).select_related(
                    "created_by__author_profile"
                ),
            ),
            Prefetch(
                "unified_document__grants__applications__preregistration_post__unified_document__fundraises",
                queryset=Fundraise.objects.prefetch_related(
                    "nonprofit_links__nonprofit",
                ),
            ),
        ]

        if include_key_insights:
            prefetch_related.append(
                Prefetch(
                    "unified_document__grants__proposal_reviews",
                    queryset=ProposalReview.objects.prefetch_related(
                        "key_insight__items"
                    ),
                )
            )

        queryset = (
            ResearchhubPost.objects.filter(unified_document__is_public=True)
            .select_related(
                "created_by",
                "created_by__author_profile",
                "unified_document",
            )
            .prefetch_related(*prefetch_related)
            .filter(document_type=GRANT, unified_document__is_removed=False)
        )

        queryset = queryset.exclude(
            unified_document__grants__status__in=[Grant.PENDING, Grant.DECLINED]
        )

        if status:
            status_upper = status.upper()
            now = timezone.now()

            if status_upper == Grant.OPEN:
                # Matches Grant.is_active(): status=OPEN and not expired
                queryset = queryset.filter(
                    Q(unified_document__grants__status=Grant.OPEN),
                    Q(unified_document__grants__end_date__isnull=True)
                    | Q(unified_document__grants__end_date__gt=now),
                )
            elif status_upper in (Grant.CLOSED, Grant.COMPLETED):
                # Inactive: explicitly closed/completed, or open but expired
                queryset = queryset.filter(
                    Q(
                        unified_document__grants__status__in=[
                            Grant.CLOSED,
                            Grant.COMPLETED,
                        ]
                    )
                    | Q(
                        unified_document__grants__status=Grant.OPEN,
                        unified_document__grants__end_date__lt=now,
                    )
                )

        if organization:
            queryset = queryset.filter(
                unified_document__grants__organization__icontains=organization
            )

        if created_by:
            queryset = queryset.filter(created_by_id=created_by)

        return queryset
