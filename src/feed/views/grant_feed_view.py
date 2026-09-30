"""
Specialized feed view focused on grant-related content for ResearchHub.
This view displays grants in a feed format, showing funding opportunities
and research grant postings.
"""

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db.models import Prefetch, Q
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import ReadOnlyModelViewSet

from ai_peer_review.models import ProposalReview
from feed.cache_segment import (
    FEED_CACHE_MAX_CACHED_PAGE,
    FEED_CACHE_PAGE_SIZE,
    FEED_CACHE_TIMEOUT,
    apply_visibility_for_segment,
    get_feed_cache_segment,
)
from feed.feed_list_dto import GrantFeedListEntrySerializer
from feed.filters import FundOrderingFilter
from feed.grant_feed_cache import (
    GRANT_FEED_WARM_ORDERINGS,
    GRANT_FEED_WARM_SEGMENTS,
    should_cache_grant_feed,
)
from feed.views.feed_view_mixin import FeedViewMixin
from feed.views.grant_cache_mixin import GrantCacheMixin
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.grant_model import Grant
from researchhub_document.related_models.constants.document_type import GRANT
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from review.models import Review
from user.models import User

from .common import FeedPagination


class GrantFeedViewSet(GrantCacheMixin, FeedViewMixin, ReadOnlyModelViewSet):
    serializer_class = GrantFeedListEntrySerializer
    permission_classes = []
    pagination_class = FeedPagination
    filter_backends = [DjangoFilterBackend, FundOrderingFilter]
    is_grant_view = True
    DEFAULT_CACHE_TIMEOUT = FEED_CACHE_TIMEOUT
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
        self._feed_cache_segment = get_feed_cache_segment(
            request, supports_private=True
        )
        cache_key = None
        if should_cache_grant_feed(request):
            cache_key = self.get_cache_key(request, "grants") + self._feed_cache_segment
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
            "unified_document__grants__funding_pool",
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
            ResearchhubPost.objects.select_related(
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

        # Organization is uncached and personalized; created_by stays uncached.
        if organization:
            queryset = queryset.visible_to(self.request.user)
        else:
            segment = getattr(self, "_feed_cache_segment", None)
            if segment is None:
                segment = get_feed_cache_segment(self.request, supports_private=True)
            queryset = apply_visibility_for_segment(queryset, self.request, segment)

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

    @classmethod
    def build_page_payload(
        cls,
        page: int,
        *,
        ordering: str | None = None,
        segment: str,
        page_size: int = FEED_CACHE_PAGE_SIZE,
    ) -> dict:
        """Serialize one homepage discovery page for cache warm."""
        params: dict[str, str] = {
            "page": str(page),
            "page_size": str(page_size),
        }
        if ordering:
            params["ordering"] = ordering

        factory = APIRequestFactory()
        wsgi_request = factory.get(
            "/api/grant_feed/",
            params,
            HTTP_HOST="researchhub.com",
        )
        request = Request(wsgi_request)
        if segment == ":admin":
            # Any mod/editor identity is fine.
            request.user = User(id=0, moderator=True)
        else:
            request.user = AnonymousUser()

        view = cls()
        view.request = request
        view.format_kwarg = None
        view.action = "list"
        view.kwargs = {}
        view.headers = {}
        view._feed_cache_segment = segment

        queryset = view.filter_queryset(view.get_queryset())
        page_items = view.paginate_queryset(queryset)
        feed_entries = [
            view.build_unsaved_feed_entry(
                post, view._post_content_type, post.created_by
            )
            for post in page_items
        ]
        serializer = GrantFeedListEntrySerializer(
            feed_entries, many=True, context=view.get_serializer_context()
        )
        return view.get_paginated_response(serializer.data).data

    @classmethod
    def warm_homepage_cache(cls) -> None:
        """Replace ``:public`` / ``:admin`` homepage keys."""
        warm_orderings: tuple[str | None, ...] = (None, *GRANT_FEED_WARM_ORDERINGS)
        for segment in GRANT_FEED_WARM_SEGMENTS:
            for ordering in warm_orderings:
                for page in range(1, FEED_CACHE_MAX_CACHED_PAGE + 1):
                    params: dict[str, str] = {
                        "page": str(page),
                        "page_size": str(FEED_CACHE_PAGE_SIZE),
                    }
                    if ordering:
                        params["ordering"] = ordering
                    factory = APIRequestFactory()
                    req = Request(factory.get("/api/grant_feed/", params))
                    req.user = AnonymousUser()
                    view = cls()
                    cache_key = view.get_cache_key(req, "grants") + segment
                    payload = cls.build_page_payload(
                        page,
                        ordering=ordering,
                        segment=segment,
                        page_size=FEED_CACHE_PAGE_SIZE,
                    )
                    cache.set(cache_key, payload, timeout=FEED_CACHE_TIMEOUT)
                    if not payload.get("results"):
                        # Feed shrank: overwrite any stale higher-page payloads.
                        for tail_page in range(
                            page + 1, FEED_CACHE_MAX_CACHED_PAGE + 1
                        ):
                            params["page"] = str(tail_page)
                            tail_req = Request(factory.get("/api/grant_feed/", params))
                            tail_req.user = AnonymousUser()
                            tail_key = view.get_cache_key(tail_req, "grants") + segment
                            cache.set(tail_key, payload, timeout=FEED_CACHE_TIMEOUT)
                        break
