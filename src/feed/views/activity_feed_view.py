from collections.abc import Sequence

from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db.models import Count, Exists, OuterRef, Prefetch, Q, QuerySet
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import ReadOnlyModelViewSet

from discussion.serializers import VoteSerializer
from feed.activity_feed_cache import (
    ACTIVITY_FEED_CACHE_PAGE_SIZE,
    ACTIVITY_FEED_CACHE_TIMEOUT,
    ACTIVITY_FEED_MAX_CACHED_PAGE,
    activity_feed_cache_key,
    should_cache_activity_feed,
)
from feed.feed_visibility import exclude_hidden_feed_entries
from feed.models import FeedEntry
from feed.serializers import ActivityFeedEntrySerializer, UserActivityQuerySerializer
from feed.services.feed_entry_visibility_service import FeedEntryVisibilityService
from feed.services.user_activity_service import UserActivityService
from feed.views.common import FeedPagination
from feed.views.feed_view_mixin import FeedViewMixin
from paper.related_models.paper_model import Paper
from purchase.models import Fundraise
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.grant_model import Grant
from purchase.related_models.purchase_model import Purchase
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from researchhub_comment.constants.rh_comment_thread_types import (
    COMMUNITY_REVIEW,
    PEER_REVIEW,
)
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    hidden_comment_ids,
)
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PAPER,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.permissions import IsModerator
from user.related_models.funding_activity_model import FundingActivity
from user.related_models.user_model import AI_EXPERT_EMAIL


class CountedFeedPagination(PageNumberPagination):
    """Feed pagination that reports the total number of matching entries."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class ActivityFeedViewSet(FeedViewMixin, ReadOnlyModelViewSet):
    """
    Feed of activity on documents, excluding paper/preprint-associated
    entries. Peer reviews are limited to proposals (PREREGISTRATION).
    Entries are limited to documents the requester is allowed to see.
    These filters apply to every request.

    Supports filtering by:
      - scope: "grants" returns all activity across every grant and
        every preregistration that applied to any grant.
        "peer_reviews" returns only peer review comments.
        "financial" returns fundraise contribution activity
        (RSC and USD contributions), approved grant post
        feed entries, bounty payouts, and review tips.
      - document_type: PREREGISTRATION, GRANT, etc.
      - grant_id: all activity on a grant and its applied preregistrations
      - content_type: RHCOMMENTMODEL, RESEARCHHUBPOST, PAPER, etc.
      - comment_type: AUTHOR_UPDATE, REVIEW, PEER_REVIEW, etc. Repeat the param
        to allow several, e.g. ?comment_type=AUTHOR_UPDATE&comment_type=REVIEW

    Filters can be combined: e.g. ?scope=grants&content_type=RHCOMMENTMODEL
    returns only comments across all grant-related documents.

    The unscoped public discovery feed (pages 1–20, page_size=20) may be served
    from a shared warm cache. Votes are attached after the cache read for
    authenticated users.
    """

    serializer_class = ActivityFeedEntrySerializer
    permission_classes = []
    pagination_class = FeedPagination

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    def add_user_votes_to_response(self, user, response_data):
        """Attach votes for related_work documents."""
        results = response_data.get("results") or []
        paper_ids: list[int] = []
        post_ids: list[int] = []

        for item in results:
            related = item.get("related_work")
            if not related or related.get("id") is None:
                continue
            work_id = int(related["id"])
            if (related.get("document_type") or "").upper() == PAPER:
                paper_ids.append(work_id)
            else:
                post_ids.append(work_id)

        paper_votes_map = {}
        if paper_ids:
            for vote in self._get_user_votes(user, paper_ids, self._paper_content_type):
                paper_votes_map[int(vote.object_id)] = VoteSerializer(vote).data

        post_votes_map = {}
        if post_ids:
            for vote in self._get_user_votes(user, post_ids, self._post_content_type):
                post_votes_map[int(vote.object_id)] = VoteSerializer(vote).data

        for item in results:
            related = item.get("related_work")
            if not related or related.get("id") is None:
                continue
            work_id = int(related["id"])
            if (related.get("document_type") or "").upper() == PAPER:
                vote_data = paper_votes_map.get(work_id)
            else:
                vote_data = post_votes_map.get(work_id)
            if not vote_data:
                continue
            related["user_vote"] = vote_data
            item["user_vote"] = vote_data

    def list(self, request, *args, **kwargs):
        cache_key = None
        if should_cache_activity_feed(request):
            page = int(request.query_params.get("page", "1"))
            cache_key = activity_feed_cache_key(page)

            cached_response = cache.get(cache_key)
            if cached_response is not None:
                if request.user.is_authenticated:
                    self.add_user_votes_to_response(request.user, cached_response)
                return Response(cached_response)

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data

        if cache_key:
            cache.set(cache_key, response_data, timeout=ACTIVITY_FEED_CACHE_TIMEOUT)

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response_data)

        return Response(response_data)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, IsModerator],
        url_path="exclude_from_feed",
    )
    def exclude_from_feed(self, request, pk=None):
        """Hide this feed entry from public feeds. Idempotent and feed-only."""
        return self._set_feed_visibility(request, pk, excluded=True)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, IsModerator],
        url_path="include_in_feed",
    )
    def include_in_feed(self, request, pk=None):
        """Restore this feed entry to public feeds. Idempotent and feed-only."""
        return self._set_feed_visibility(request, pk, excluded=False)

    def _set_feed_visibility(self, request, pk, excluded: bool):
        if pk is None or not str(pk).isdigit():
            return Response(status=status.HTTP_404_NOT_FOUND)

        service = FeedEntryVisibilityService()
        try:
            if excluded:
                feed_entry = service.exclude_from_feed(int(pk), request.user)
            else:
                feed_entry = service.include_in_feed(int(pk))
        except FeedEntry.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        return Response({"id": feed_entry.id, "is_excluded_in_feed": excluded})

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[IsAuthenticated, IsModerator],
        url_path="excluded_from_feed",
    )
    def excluded_from_feed(self, request):
        """Paginated feed entries currently hidden from public feeds."""
        queryset = FeedEntryVisibilityService().list_excluded_from_feed(
            query=request.query_params.get("query")
        )
        paginator = CountedFeedPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = ActivityFeedEntrySerializer(
            page, many=True, context=self.get_serializer_context()
        )
        return paginator.get_paginated_response(serializer.data)

    @action(
        detail=False,
        methods=["get"],
        url_path="user_activity",
        url_name="user-activity",
        permission_classes=[IsAuthenticated],
        pagination_class=CountedFeedPagination,
    )
    def list_user_activity(self, request: Request) -> Response:
        """Return activity on documents the requested user is involved with.

        Requires ``user_id``. Only that user, a moderator, or a hub editor may
        read it.
        """
        query_serializer = UserActivityQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        user_id = query_serializer.validated_data["user_id"]
        if user_id != request.user.id and not request.user.is_moderator_or_editor():
            raise PermissionDenied("Cannot view another user's activity.")

        document_ids = UserActivityService().get_involved_document_ids(user_id)
        queryset = self.filter_queryset(self.get_queryset()).filter(
            unified_document_id__in=document_ids
        )
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response = self.get_paginated_response(serializer.data)
        self.add_user_votes_to_response(request.user, response.data)
        return response

    def get_queryset(self):
        queryset = (
            FeedEntry.objects.select_related(
                "content_type",
                "unified_document",
                "user",
                "user__author_profile",
                "user__userverification",
                "unified_document__paper__uploaded_by__author_profile",
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
            .order_by("-action_date")
        )
        queryset = exclude_hidden_feed_entries(queryset)

        # Exclude paper publications
        paper_ct = ContentType.objects.get_for_model(Paper)
        queryset = queryset.exclude(content_type=paper_ct)
        queryset = queryset.exclude(user__is_active=False)

        comment_ct = ContentType.objects.get_for_model(RhCommentModel)
        queryset = queryset.exclude(
            content_type=comment_ct,
            object_id__in=hidden_comment_ids(),
        )
        queryset = queryset.exclude(
            content_type=comment_ct,
            user__email=AI_EXPERT_EMAIL,
        )
        queryset = self._exclude_paper_documents(queryset)
        queryset = self._exclude_non_proposal_peer_reviews(queryset)

        scope = self.request.query_params.get("scope", "").lower()
        grant_id = self.request.query_params.get("grant_id")

        # Unscoped list is a shared cached public page. Scoped, grant, and
        # non-list requests are per-requester so grant owners can see
        # private applications.
        is_discovery = self.action == "list" and not scope and not grant_id
        visible_posts = (
            ResearchhubPost.objects.publicly_visible()
            if is_discovery
            else ResearchhubPost.objects.visible_to(self.request.user)
        )
        queryset = queryset.filter(
            unified_document_id__in=visible_posts.values("unified_document_id"),
            unified_document__is_removed=False,
        )

        if grant_id:
            queryset = self._filter_by_grant(queryset, grant_id)

        if scope == "grants" and not grant_id:
            queryset = self._filter_all_grants(queryset)
        elif scope == "peer_reviews":
            queryset = self._filter_peer_reviews(queryset)
        elif scope == "financial":
            queryset = self._filter_financial_activities(queryset)
        elif not grant_id:
            document_type = self.request.query_params.get("document_type")
            if document_type:
                queryset = queryset.filter(
                    unified_document__document_type=(document_type.upper())
                )

        content_type = self.request.query_params.get("content_type")
        if content_type:
            queryset = self._filter_by_content_type(queryset, content_type)

        comment_types = self.request.query_params.getlist("comment_type")
        if comment_types:
            queryset = self._filter_by_comment_type(queryset, comment_types)

        return queryset

    @classmethod
    def build_page_payload(
        cls,
        page: int,
        page_size: int = ACTIVITY_FEED_CACHE_PAGE_SIZE,
    ) -> dict:
        """Serialize one unscoped public discovery page (for cache warm)."""
        factory = APIRequestFactory()
        wsgi_request = factory.get(
            "/api/activity_feed/",
            {"page": str(page), "page_size": str(page_size)},
            HTTP_HOST="researchhub.com",
        )
        request = Request(wsgi_request)
        request.user = AnonymousUser()

        view = cls()
        view.request = request
        view.format_kwarg = None
        view.action = "list"
        view.kwargs = {}
        view.headers = {}

        queryset = view.filter_queryset(view.get_queryset())
        page_items = view.paginate_queryset(queryset)
        serializer = view.get_serializer(page_items, many=True)
        return view.get_paginated_response(serializer.data).data

    @classmethod
    def warm_public_cache(cls) -> None:
        """Replace cached payloads for pages 1–MAX with fresh public data."""
        for page in range(1, ACTIVITY_FEED_MAX_CACHED_PAGE + 1):
            payload = cls.build_page_payload(page)
            cache.set(
                activity_feed_cache_key(page),
                payload,
                timeout=ACTIVITY_FEED_CACHE_TIMEOUT,
            )

    @staticmethod
    def _filter_by_grant(queryset, grant_id):
        """
        Return feed entries for a grant and all preregistrations
        that applied to it. This covers:
          - posts/comments on the grant document itself
          - posts/comments on preregistration documents applied
            to this grant (via GrantApplication)
        """
        try:
            grant = Grant.objects.get(pk=grant_id)
        except Grant.DoesNotExist:
            return queryset.none()

        ud_ids = {grant.unified_document_id}

        prereg_ud_ids = GrantApplication.objects.filter(
            grant=grant,
        ).values_list(
            "preregistration_post__unified_document_id",
            flat=True,
        )
        ud_ids.update(prereg_ud_ids)

        return queryset.filter(unified_document_id__in=ud_ids)

    @staticmethod
    def _filter_all_grants(queryset):
        """
        Return feed entries for every grant document and every
        preregistration that has applied to any grant.
        Excludes PENDING and DECLINED grants (moderation-only).
        """
        grant_ud_ids = (
            Grant.objects.exclude(status__in=[Grant.PENDING, Grant.DECLINED])
            .filter(unified_document__is_public=True)
            .values_list("unified_document_id", flat=True)
        )
        prereg_ud_ids = GrantApplication.objects.values_list(
            "preregistration_post__unified_document_id",
            flat=True,
        )
        all_ud_ids = set(grant_ud_ids) | set(prereg_ud_ids)
        return queryset.filter(unified_document_id__in=all_ud_ids)

    @staticmethod
    def _exclude_paper_documents(queryset):
        """Drop entries whose parent document is a paper/preprint."""
        return queryset.exclude(unified_document__document_type=PAPER)

    @staticmethod
    def _exclude_non_proposal_peer_reviews(queryset):
        """Drop peer reviews that are not on a proposal."""
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)
        peer_review_ids = RhCommentModel.objects.filter(
            comment_type__in=[PEER_REVIEW, COMMUNITY_REVIEW],
        ).values("id")

        return queryset.exclude(
            Q(content_type=comment_ct, object_id__in=peer_review_ids)
            & ~Q(unified_document__document_type=PREREGISTRATION)
        )

    @staticmethod
    def _filter_peer_reviews(queryset):
        """
        Return feed entries that are peer review comments.
        """
        comment_type = ContentType.objects.get_for_model(RhCommentModel)
        peer_review_ids = RhCommentModel.objects.filter(
            comment_type__in=[PEER_REVIEW, COMMUNITY_REVIEW],
        ).values("id")

        return queryset.filter(
            content_type=comment_type,
            object_id__in=peer_review_ids,
        )

    @staticmethod
    def _filter_financial_activities(queryset):
        """
        Return feed entries for fundraise contributions, grant post
        publications, bounty payouts, and review tips.
        """
        purchase_type = ContentType.objects.get_for_model(Purchase)
        usd_contribution_type = ContentType.objects.get_for_model(
            UsdFundraiseContribution
        )
        post_ct = ContentType.objects.get_for_model(ResearchhubPost)
        fa_ct = ContentType.objects.get_for_model(FundingActivity)
        contribution_purchase_ids = Purchase.objects.filter(
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION
        ).values_list("id", flat=True)
        financial_funding_activity = FundingActivity.objects.filter(
            id=OuterRef("object_id"),
            source_type__in=[
                FundingActivity.BOUNTY_PAYOUT,
                FundingActivity.TIP_REVIEW,
            ],
        )

        return queryset.filter(
            Q(
                content_type=purchase_type,
                object_id__in=contribution_purchase_ids,
            )
            | Q(content_type=usd_contribution_type)
            | Q(
                content_type=post_ct,
                unified_document__document_type=GRANT,
            )
            | (Q(content_type=fa_ct) & Q(Exists(financial_funding_activity)))
        )

    @staticmethod
    def _filter_by_content_type(queryset, content_type_name):
        """Filter feed entries by the model name of their content_type."""
        try:
            ct = ContentType.objects.get(model=content_type_name.lower())
        except ContentType.DoesNotExist:
            return queryset.none()
        return queryset.filter(content_type=ct)

    @staticmethod
    def _filter_by_comment_type(
        queryset: QuerySet[FeedEntry],
        comment_types: Sequence[str],
    ) -> QuerySet[FeedEntry]:
        """Return feed entries for comments of the given comment types."""
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)
        comment_ids = RhCommentModel.objects.filter(
            comment_type__in=[value.upper() for value in comment_types],
        ).values("id")

        return queryset.filter(content_type=comment_ct, object_id__in=comment_ids)
