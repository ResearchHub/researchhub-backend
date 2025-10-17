"""
Specialized feed view focused on grant-related content for ResearchHub.
This view displays grants in a feed format, showing funding opportunities
and research grant postings.
"""

from django.core.cache import cache
from django.db.models import Case, DecimalField, Exists, IntegerField, OuterRef, Prefetch, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from feed.models import FeedEntry
from feed.views.fund_serializer import serialize_feed_entry_fund
from feed.views.feed_view_mixin import FeedViewMixin
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.grant_model import Grant
from researchhub_document.related_models.constants.document_type import GRANT
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

from .common import FeedPagination


class GrantFeedViewSet(FeedViewMixin, ModelViewSet):
    """
    ViewSet for accessing entries specifically related to grant documents.
    This provides a dedicated endpoint for clients to fetch and display grant
    content in the Research Hub platform.

    Query Parameters:
    - status: Filter by grant status
      Options:
        - OPEN: Only show posts with open grants
        - CLOSED: Only show posts with closed grants
        - COMPLETED: Only show posts with completed grants
    - organization: Filter by granting organization name (partial match)
    - ordering: Sort order
      Options:
        - newest (default): Sort by creation date (newest first)
        - hot_score: Sort by trending score (most engaging content)
        - upvotes: Sort by score (most upvoted first)
        - amount_raised: Sort by amount raised (highest first)
    """

    permission_classes = []
    pagination_class = FeedPagination

    def _apply_ordering(self, queryset, ordering):
        """Apply ordering with status priority for grants."""
        order_fields = {
            "hot_score": ("status_priority", "-unified_document__hot_score", "id"),
            "upvotes": ("status_priority", "-score", "id"),
            "amount_raised": None,
        }.get(ordering, ("status_priority", "-created_date", "id"))
        
        if ordering == "amount_raised":
            queryset = queryset.annotate(
                grant_amount=Coalesce(
                    Sum("unified_document__grants__amount"), 0, output_field=DecimalField()
                )
            )
            return queryset.order_by("status_priority", "-grant_amount", "id")
        
        return queryset.order_by(*order_fields)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    def get_cache_key(self, request, feed_type=""):
        base_key = super().get_cache_key(request, feed_type)
        params = [
            request.query_params.get("status", ""),
            request.query_params.get("organization", ""),
            request.query_params.get("ordering", "")
        ]
        return f"{base_key}-{':'.join(params)}-v16-hub-opt"

    def list(self, request, *args, **kwargs):
        page = request.query_params.get("page", "1")
        page_num = int(page)
        status = request.query_params.get("status", None)
        organization = request.query_params.get("organization", None)
        ordering = request.query_params.get("ordering", None)
        cache_key = self.get_cache_key(request, "grants")
        use_cache = page_num < 4 and status is None and organization is None and ordering is None

        if use_cache:
            # try to get cached response
            cached_response = cache.get(cache_key)
            if cached_response:
                if request.user.is_authenticated:
                    self.add_user_votes_to_response(request.user, cached_response)
                return Response(cached_response)

        # Get paginated posts
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)

        # Ultra-fast serialization - bypass DRF completely
        results = []
        for post in page:
            # Create an unsaved FeedEntry instance
            feed_entry = FeedEntry(
                id=post.id,
                content_type=self._post_content_type,
                object_id=post.id,
                action="PUBLISH",
                action_date=post.created_date,
                user=post.created_by,
                unified_document=post.unified_document,
            )
            feed_entry.item = post
            
            # Use ultra-fast serialization
            serialized = serialize_feed_entry_fund(feed_entry, request)
            results.append(serialized)
        
        # Build response data manually
        response_data = self.get_paginated_response(results).data

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response_data)

        if use_cache:
            cache.set(cache_key, response_data, timeout=self.DEFAULT_CACHE_TIMEOUT)

        return Response(response_data)

    def get_queryset(self):
        """Filter to posts with grants, prioritizing active ones."""
        status = self.request.query_params.get("status")
        organization = self.request.query_params.get("organization")
        ordering = self.request.query_params.get("ordering")

        queryset = self._build_base_queryset()
        
        if status and status.upper() in [Grant.OPEN, Grant.CLOSED, Grant.COMPLETED]:
            queryset = queryset.filter(unified_document__grants__status=status.upper())
        
        if organization:
            queryset = queryset.filter(unified_document__grants__organization__icontains=organization)
        
        return self._apply_ordering(queryset, ordering).distinct()

    def _build_base_queryset(self):
        """Build base queryset with status_priority annotation and optimized prefetch."""
        now = timezone.now()
        
        # Optimized Exists subquery - the composite index makes this fast
        has_active = Grant.objects.filter(
            unified_document_id=OuterRef("unified_document_id"),
            status=Grant.OPEN
        ).filter(Q(end_date__isnull=True) | Q(end_date__gt=now))
        
        # Prefetch grants with applications  
        applications_prefetch = Prefetch(
            "applications",
            queryset=GrantApplication.objects.select_related(
                "applicant__author_profile__user"
            )
        )
        
        grant_prefetch = Prefetch(
            "unified_document__grants",
            queryset=Grant.objects.select_related(
                "created_by__author_profile__user"
            ).prefetch_related(
                applications_prefetch
            ).order_by("end_date")
        )
        
        return ResearchhubPost.objects.select_related(
            "created_by__author_profile__user", "unified_document"
        ).prefetch_related(
            "unified_document__hubs", grant_prefetch
        ).filter(
            document_type=GRANT, unified_document__is_removed=False
        ).annotate(
            status_priority=Case(
                When(Exists(has_active), then=Value(0)),
                default=Value(1),
                output_field=IntegerField()
            )
        )
