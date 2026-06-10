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
from feed.filters import FundOrderingFilter
from feed.models import FeedEntry
from feed.serializers import GrantFeedEntrySerializer
from feed.views.feed_view_mixin import FeedViewMixin
from feed.views.grant_cache_mixin import GRANT_FEED_MAX_CACHED_PAGE, GrantCacheMixin
from purchase.models import GrantApplication
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.grant_model import Grant
from purchase.related_models.purchase_model import Purchase
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from purchase.serializers import DynamicGrantSerializer
from researchhub_document.related_models.constants.document_type import GRANT
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from review.models import Review

from ..serializers import PostSerializer, serialize_feed_metrics
from .common import FeedPagination


class GrantFeedViewSet(GrantCacheMixin, FeedViewMixin, ModelViewSet):
    serializer_class = PostSerializer
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
        return context

    def list(self, request, *args, **kwargs):
        page = request.query_params.get("page", "1")
        page_num = int(page)
        cache_key = self.get_cache_key(request, "grants")
        use_cache = page_num <= GRANT_FEED_MAX_CACHED_PAGE

        if use_cache:
            cached_response = cache.get(cache_key)
            if cached_response:
                if request.user.is_authenticated:
                    self.add_user_votes_to_response(request.user, cached_response)
                    self.add_private_applications_to_response(
                        request.user, cached_response
                    )
                return Response(cached_response)

        # Get paginated posts
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        feed_entries = []
        for post in page:
            # Create an unsaved FeedEntry instance
            feed_entry = FeedEntry(
                id=post.id,  # We can use the post ID as a temporary ID
                content_type=self._post_content_type,
                object_id=post.id,
                action="PUBLISH",
                action_date=post.created_date,
                user=post.created_by,
                unified_document=post.unified_document,
            )
            feed_entry.item = post
            metrics = serialize_feed_metrics(post, self._post_content_type)
            feed_entry.metrics = metrics
            feed_entries.append(feed_entry)

        serializer = GrantFeedEntrySerializer(feed_entries, many=True)
        response_data = self.get_paginated_response(serializer.data).data

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response_data)

        if use_cache:
            cache.set(cache_key, response_data, timeout=self.DEFAULT_CACHE_TIMEOUT)

        # Merge private applications in AFTER caching: the cached payload is
        # shared across all viewers, so it must stay public-only. Private
        # proposals are added per-request for the viewers allowed to see them.
        if request.user.is_authenticated:
            self.add_private_applications_to_response(request.user, response_data)

        return Response(response_data)

    def add_private_applications_to_response(self, user, response_data):
        """Inject the private grant applications this viewer is allowed to see.

        The cached grant feed payload is shared across every user, so it only
        ever carries public applications (it is serialized without a request
        context). After reading the payload — fresh or from cache — we merge in
        the private preregistration applications visible to this specific user,
        using ResearchhubPost.visible_to() as the single source of truth for
        visibility (grant owner, applicant, invited experts with a Permission,
        moderators and hub editors). This mirrors add_user_votes_to_response,
        which likewise personalizes the shared cache per request.
        """
        post_type_str = self._post_content_type.model.upper()

        # Map each grant id to its applications list in the response, and track
        # which application ids are already present so we never duplicate one.
        grant_apps = {}
        seen_app_ids = set()
        for item in response_data.get("results", []):
            if item.get("content_type") != post_type_str:
                continue
            grant = (item.get("content_object") or {}).get("grant")
            if not grant or "id" not in grant:
                continue
            applications = grant.setdefault("applications", [])
            grant_apps.setdefault(grant["id"], applications)
            for app in applications:
                seen_app_ids.add(app["id"])

        if not grant_apps:
            return

        visible_private_posts = ResearchhubPost.objects.visible_to(user).filter(
            unified_document__is_public=False,
            unified_document__is_removed=False,
        )
        applications = (
            GrantApplication.objects.filter(
                grant_id__in=grant_apps.keys(),
                preregistration_post__in=visible_private_posts,
            )
            .select_related(
                # The applicant serializer's is_verified field reads
                # author_profile.user.userverification. select_related on the
                # reverse one-to-one back-populates author_profile.user with the
                # applicant instance itself, so userverification must hang off
                # applicant (not applicant__author_profile__user) to be cached.
                # grant is joined because review_by_ud reads
                # grant.proposal_reviews.
                "grant",
                "applicant__author_profile",
                "applicant__userverification",
                "preregistration_post__unified_document",
            )
            .prefetch_related(
                "grant__proposal_reviews__key_insight__items",
                Prefetch(
                    "preregistration_post__unified_document__reviews",
                    queryset=Review.objects.filter(is_removed=False).select_related(
                        "created_by__author_profile"
                    ),
                ),
                Prefetch(
                    "preregistration_post__unified_document__fundraises",
                    queryset=Fundraise.objects.select_related(
                        "escrow"
                    ).prefetch_related(
                        Prefetch(
                            "purchases",
                            queryset=Purchase.objects.select_related(
                                "user__author_profile"
                            ),
                            to_attr="prefetched_purchases",
                        ),
                        Prefetch(
                            "usd_contributions",
                            queryset=UsdFundraiseContribution.objects.select_related(
                                "user__author_profile"
                            ),
                            to_attr="prefetched_usd_contributions",
                        ),
                        "nonprofit_links__nonprofit",
                    ),
                ),
            )
        )

        for application in applications:
            if application.id in seen_app_ids:
                continue
            target = grant_apps.get(application.grant_id)
            if target is None:
                continue
            review_by_ud = {
                r.unified_document_id: r
                for r in application.grant.proposal_reviews.all()
            }
            serialized = DynamicGrantSerializer._serialize_application(
                application, review_by_ud
            )
            if serialized is None:
                continue
            target.append(serialized)
            seen_app_ids.add(application.id)

    def get_queryset(self):
        status = self.request.query_params.get("status")
        organization = self.request.query_params.get("organization")
        created_by = self.request.query_params.get("created_by")

        queryset = (
            ResearchhubPost.objects.filter(unified_document__is_public=True)
            .select_related(
                "created_by",
                "created_by__author_profile",
                "unified_document",
            )
            .prefetch_related(
                "unified_document__hubs",
                Prefetch(
                    "unified_document__reviews",
                    queryset=Review.objects.select_related(
                        "created_by__author_profile"
                    ),
                ),
                Prefetch(
                    "unified_document__grants__proposal_reviews",
                    queryset=ProposalReview.objects.prefetch_related(
                        "key_insight__items"
                    ),
                ),
                "unified_document__grants__applications__applicant__author_profile",
                Prefetch(
                    "unified_document__grants__applications__preregistration_post__unified_document__reviews",
                    queryset=Review.objects.filter(is_removed=False).select_related(
                        "created_by__author_profile"
                    ),
                ),
                Prefetch(
                    "unified_document__grants__applications__preregistration_post__unified_document__fundraises",
                    queryset=Fundraise.objects.select_related(
                        "escrow"
                    ).prefetch_related(
                        Prefetch(
                            "purchases",
                            queryset=Purchase.objects.select_related(
                                "user__author_profile"
                            ),
                            to_attr="prefetched_purchases",
                        ),
                        Prefetch(
                            "usd_contributions",
                            queryset=UsdFundraiseContribution.objects.select_related(
                                "user__author_profile"
                            ),
                            to_attr="prefetched_usd_contributions",
                        ),
                        "nonprofit_links__nonprofit",
                    ),
                ),
            )
            .filter(document_type=GRANT, unified_document__is_removed=False)
        )

        if status and status.upper() == Grant.PENDING:
            queryset = queryset.filter(unified_document__grants__status=Grant.PENDING)
        else:
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
