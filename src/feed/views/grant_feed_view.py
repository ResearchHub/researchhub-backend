"""
Specialized feed view focused on grant-related content for ResearchHub.
This view displays grants in a feed format, showing funding opportunities
and research grant postings.
"""

from django.db.models import Case, DecimalField, Exists, IntegerField, OuterRef, Prefetch, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.filters import OrderingFilter
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
        - -created_date (default): Sort by creation date (newest first)
        - -unified_document__hot_score: Sort by trending score (most engaging content)
        - -score: Sort by score (most upvoted first)
        - -grant_amount: Sort by grant amount (highest first)
    """

    permission_classes = []
    pagination_class = FeedPagination
    filter_backends = [OrderingFilter]
    ordering_fields = ['created_date', 'score', 'unified_document__hot_score', 'grant_amount']
    ordering = ['status_priority', '-created_date', 'id']

    def filter_queryset(self, queryset):
        """
        Override to ensure status_priority is always the primary sort field.
        This maintains OPEN items before CLOSED items regardless of secondary sort.
        """
        queryset = super().filter_queryset(queryset)
        
        # Get the ordering parameter
        ordering_param = self.request.query_params.get(self.ordering_param, '')
        
        # Handle special case for grant_amount (needs annotation)
        if 'grant_amount' in ordering_param:
            queryset = queryset.annotate(
                grant_amount=Coalesce(
                    Sum("unified_document__grants__amount"), 0, output_field=DecimalField()
                )
            )
        
        # Get current ordering from queryset
        current_ordering = list(queryset.query.order_by) if queryset.query.order_by else []
        
        # Ensure status_priority is always first
        if current_ordering:
            # Remove status_priority if it exists anywhere in the list
            current_ordering = [f for f in current_ordering if f not in ['status_priority', '-status_priority']]
            # Prepend status_priority
            new_ordering = ['status_priority'] + current_ordering
            # Ensure 'id' is last for consistent tie-breaking
            if 'id' not in new_ordering and '-id' not in new_ordering:
                new_ordering.append('id')
            queryset = queryset.order_by(*new_ordering)
        
        return queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    def get_cache_key(self, request, feed_type=""):
        base_key = super().get_cache_key(request, feed_type)
        status = request.query_params.get("status", "")
        organization = request.query_params.get("organization", "")
        ordering = request.query_params.get("ordering", "")
        return f"{base_key}-{status}:{organization}:{ordering}"

    def list(self, request, *args, **kwargs):
        from django.conf import settings
        
        page = request.query_params.get("page", "1")
        page_num = int(page)
        status = request.query_params.get("status", None)
        organization = request.query_params.get("organization", None)
        ordering = request.query_params.get("ordering", None)
        cache_key = self.get_cache_key(request, "grants")
        
        # Updated to match new OrderingFilter parameter format
        cacheable_orderings = {None, "-created_date", "-unified_document__hot_score", "-score", "-grant_amount"}
        cacheable_statuses = {None, "OPEN", "CLOSED"}
        
        use_cache = (
            page_num <= 4 and 
            organization is None and
            ordering in cacheable_orderings and
            (status.upper() if status else None) in cacheable_statuses
        )
        
        return self._list_fund_entries(request, cache_key, use_cache)

    def get_queryset(self):
        status = self.request.query_params.get("status")
        organization = self.request.query_params.get("organization")

        queryset = self._build_base_queryset()
        
        if status and status.upper() in [Grant.OPEN, Grant.CLOSED, Grant.COMPLETED]:
            queryset = queryset.filter(unified_document__grants__status=status.upper())
        
        if organization:
            queryset = queryset.filter(unified_document__grants__organization__icontains=organization)
        
        return queryset

    def _build_base_queryset(self):
        now = timezone.now()
        
        # Subquery to check if post has any active (open and not expired) grants
        has_active = Grant.objects.filter(
            unified_document_id=OuterRef("unified_document_id"),
            status=Grant.OPEN
        ).filter(Q(end_date__isnull=True) | Q(end_date__gt=now)).values('pk')[:1]
        
        # Prefetch grants with related data to avoid N+1 queries
        grant_prefetch = Prefetch(
            "unified_document__grants",
            queryset=Grant.objects.select_related(
                # Fetch grant creator's user data in a single query
                "created_by__author_profile__user"
            ).prefetch_related(
                Prefetch(
                    # Fetch all applications for each grant with applicant data
                    "applications",
                    queryset=GrantApplication.objects.select_related(
                        "applicant__author_profile__user"
                    ).order_by("created_date")
                )
            ).annotate(
                # Flag to indicate if grant deadline has passed
                is_expired_flag=Case(
                    When(end_date__lt=now, then=Value(True)),
                    default=Value(False),
                    output_field=IntegerField()
                ),
                # Flag to indicate if grant is currently accepting applications
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
            # Fetch post creator's user data in a single query to avoid N+1
            "created_by__author_profile__user",
            # Fetch unified document to avoid additional queries
            "unified_document"
        ).prefetch_related(
            # Fetch all hubs associated with the document
            "unified_document__hubs",
            # Fetch grants with applications and related user data
            grant_prefetch
        ).filter(
            # Only show grant posts that haven't been removed
            document_type=GRANT,
            unified_document__is_removed=False
        ).annotate(
            # Priority field: 0 for open/active grants, 1 for closed/expired
            # Used to sort open items before closed items
            status_priority=Case(
                When(Exists(has_active), then=Value(0)),
                default=Value(1),
                output_field=IntegerField()
            )
        )
