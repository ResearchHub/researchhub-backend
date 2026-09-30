"""
Specialized feed view focused on funding-related content for ResearchHub.
This view uses the Feed serializer on preregistration posts, instantiating
feed entries for each post instead of querying the feed table.
This is done for three reasons:
1. To provide a consistent endpoint for feed content.
2. Avoid filtering on feed entries which can be expensive since it is a large table.
3. Older feed entries are not in the feed table.
"""

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db.models import Count, Prefetch, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import ReadOnlyModelViewSet

from feed.cache_segment import (
    FEED_CACHE_MAX_CACHED_PAGE,
    FEED_CACHE_PAGE_SIZE,
    FEED_CACHE_TIMEOUT,
    apply_visibility_for_segment,
    get_feed_cache_segment,
)
from feed.feed_list_dto import (
    FundingFeedListEntrySerializer,
    serialize_fund_feed_metrics,
)
from feed.filters import FundOrderingFilter
from feed.funding_feed_cache import (
    FUNDING_FEED_WARM_COMPLETED_STATUS,
    FUNDING_FEED_WARM_ORDERINGS,
    FUNDING_FEED_WARM_SEGMENTS,
    should_cache_funding_feed,
)
from feed.views.feed_view_mixin import FeedViewMixin
from feed.views.funding_cache_mixin import FundingCacheMixin
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
from user.models import User

from .common import FeedPagination


class FundingFeedViewSet(FundingCacheMixin, FeedViewMixin, ReadOnlyModelViewSet):
    """Moderators and hub editors may pass ``?include_private=true|1``to force
    an uncached ``visible_to`` read."""

    serializer_class = FundingFeedListEntrySerializer
    permission_classes = []
    pagination_class = FeedPagination
    filter_backends = [DjangoFilterBackend, FundOrderingFilter]
    ordering_fields = ["newest", "best", "upvotes", "most_applicants", "amount_raised"]
    ordering = "best"  # Default ordering
    DEFAULT_CACHE_TIMEOUT = FEED_CACHE_TIMEOUT

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    @staticmethod
    def _include_private_for_privileged(request) -> bool:
        """Whether this request forces uncached private inclusion."""
        param = request.query_params.get("include_private", "").lower()
        if param not in ("true", "1"):
            return False
        user = getattr(request, "user", None)
        return bool(
            user
            and getattr(user, "is_authenticated", False)
            and user.is_moderator_or_editor()
        )

    def list(self, request, *args, **kwargs):
        self._include_private = self._include_private_for_privileged(request)
        self._feed_cache_segment = get_feed_cache_segment(
            request, supports_private=True
        )
        cache_key = None
        if should_cache_funding_feed(request):
            cache_key = (
                self.get_cache_key(request, "funding") + self._feed_cache_segment
            )
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
        annotated_grants = (
            Grant.objects.annotate(
                num_applicants=Count(
                    application_lookup,
                    distinct=True,
                    filter=Q(**approved_proposal_filters(application_lookup)),
                )
            )
            .select_related("funding_pool")
            .prefetch_related("unified_document__posts")
        )

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
                "author_links",
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

        # Personalized feeds (grant_id / created_by / funded_by) and
        # include_private bypass are never cached — see should_cache_funding_feed.
        include_private = getattr(self, "_include_private", None)
        if include_private is None:
            include_private = self._include_private_for_privileged(self.request)
        if grant_id or created_by or funded_by or include_private:
            queryset = queryset.visible_to(self.request.user)
        else:
            segment = getattr(self, "_feed_cache_segment", None)
            if segment is None:
                segment = get_feed_cache_segment(self.request, supports_private=True)
            queryset = apply_visibility_for_segment(queryset, self.request, segment)

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

    @classmethod
    def build_page_payload(
        cls,
        page: int,
        *,
        ordering: str | None = None,
        fundraise_status: str | None = None,
        segment: str,
        page_size: int = FEED_CACHE_PAGE_SIZE,
    ) -> dict:
        """Serialize one funding-feed page for cache warm."""
        params: dict[str, str] = {
            "page": str(page),
            "page_size": str(page_size),
        }
        if ordering:
            params["ordering"] = ordering
        if fundraise_status:
            params["fundraise_status"] = fundraise_status

        factory = APIRequestFactory()
        wsgi_request = factory.get(
            "/api/funding_feed/",
            params,
            HTTP_HOST="researchhub.com",
        )
        request = Request(wsgi_request)
        if segment == ":admin":
            request.user = User(id=0, moderator=True)
        else:
            request.user = AnonymousUser()

        view = cls()
        view.request = request
        view.format_kwarg = None
        view.action = "list"
        view.kwargs = {}
        view.headers = {}
        view._include_private = False
        view._feed_cache_segment = segment

        queryset = view.filter_queryset(view.get_queryset())
        page_items = view.paginate_queryset(queryset)
        feed_entries = []
        for post in page_items:
            feed_entry = view.build_unsaved_feed_entry(
                post, view._post_content_type, post.created_by
            )
            feed_entry.metrics = serialize_fund_feed_metrics(
                post, view._post_content_type
            )
            feed_entries.append(feed_entry)
        serializer = FundingFeedListEntrySerializer(
            feed_entries, many=True, context=view.get_serializer_context()
        )
        return view.get_paginated_response(serializer.data).data

    @classmethod
    def warm_homepage_cache(cls) -> None:
        """Replace ``:public`` / ``:admin`` homepage keys."""
        warm_specs: list[tuple[str | None, str | None]] = [
            (None, None),
            *((ordering, None) for ordering in FUNDING_FEED_WARM_ORDERINGS),
            (None, FUNDING_FEED_WARM_COMPLETED_STATUS),
        ]
        for segment in FUNDING_FEED_WARM_SEGMENTS:
            for ordering, fundraise_status in warm_specs:
                for page in range(1, FEED_CACHE_MAX_CACHED_PAGE + 1):
                    params: dict[str, str] = {
                        "page": str(page),
                        "page_size": str(FEED_CACHE_PAGE_SIZE),
                    }
                    if ordering:
                        params["ordering"] = ordering
                    if fundraise_status:
                        params["fundraise_status"] = fundraise_status
                    factory = APIRequestFactory()
                    req = Request(factory.get("/api/funding_feed/", params))
                    req.user = AnonymousUser()
                    view = cls()
                    cache_key = view.get_cache_key(req, "funding") + segment
                    payload = cls.build_page_payload(
                        page,
                        ordering=ordering,
                        fundraise_status=fundraise_status,
                        segment=segment,
                        page_size=FEED_CACHE_PAGE_SIZE,
                    )
                    cache.set(cache_key, payload, timeout=FEED_CACHE_TIMEOUT)
                    if not payload.get("results"):
                        break
