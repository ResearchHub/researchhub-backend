"""
Specialized feed view focused on grant-related content for ResearchHub.
This view displays grants in a feed format, showing funding opportunities
and research grant postings.
"""

from django.db.models import Case, DecimalField, Exists, IntegerField, OuterRef, Prefetch, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.viewsets import ModelViewSet

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
        return f"{base_key}-{':'.join(params)}-v4"

    def list(self, request, *args, **kwargs):
        page = request.query_params.get("page", "1")
        page_num = int(page)
        status = request.query_params.get("status", None)
        organization = request.query_params.get("organization", None)
        ordering = request.query_params.get("ordering", None)
        cache_key = self.get_cache_key(request, "grants")
        use_cache = page_num < 4 and status is None and organization is None and ordering is None
        
        return self._list_fund_entries(request, cache_key, use_cache, "grants")

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
        now = timezone.now()
        
        has_active = Grant.objects.filter(
            unified_document_id=OuterRef("unified_document_id"),
            status=Grant.OPEN
        ).filter(Q(end_date__isnull=True) | Q(end_date__gt=now))
        
        grant_prefetch = Prefetch(
            "unified_document__grants",
            queryset=Grant.objects.select_related(
                "created_by__author_profile__user"
            ).prefetch_related(
                Prefetch(
                    "applications",
                    queryset=GrantApplication.objects.select_related(
                        "applicant__author_profile__user"
                    ).order_by("created_date")
                )
            ).annotate(
                is_expired_flag=Case(
                    When(end_date__lt=now, then=Value(True)),
                    default=Value(False),
                    output_field=IntegerField()
                ),
                is_active_flag=Case(
                    When(
                        Q(status=Grant.OPEN) & (Q(end_date__isnull=True) | Q(end_date__gte=now)),
                        then=Value(True)
                    ),
                    default=Value(False),
                    output_field=IntegerField()
                )
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
