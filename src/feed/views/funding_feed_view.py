"""
Specialized feed view focused on funding-related content for ResearchHub.
This view uses the Feed serializer on preregistration posts, instantiating
feed entries for each post instead of querying the feed table.
This is done for three reasons:
1. To provide a consistent endpoint for feed content.
2. Avoid filtering on feed entries which can be expensive since it is a large table.
3. Older feed entries are not in the feed table.
"""

from django.contrib.contenttypes.models import ContentType
from django.db.models import (
    Case,
    Count,
    DateTimeField,
    DecimalField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.filters import OrderingFilter
from rest_framework.viewsets import ModelViewSet

from feed.views.feed_view_mixin import FeedViewMixin
from purchase.models import Purchase
from purchase.related_models.fundraise_model import Fundraise
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

from .common import FeedPagination


class FundingFeedViewSet(FeedViewMixin, ModelViewSet):
    """
    ViewSet for accessing entries specifically related to preregistration documents.
    This provides a dedicated endpoint for clients to fetch and display preregistration
    content in the Research Hub platform.

    Query Parameters:
    - fundraise_status: Filter by fundraise status
      Options:
        - OPEN: Only show posts with open fundraises
        - CLOSED: Only show posts with completed fundraises
    - grant_id: Filter by grant applications
      (show only posts that applied to specific grant)
    - created_by: Filter by user ID who created the funding post
    - ordering: Sort order
      Options:
        - -created_date (default): Sort by creation date (newest first)
        - -unified_document__hot_score: Sort by trending score (most engaging content)
        - -score: Sort by score (most upvoted first)
        - -amount_raised: Sort by amount raised (highest first)
    """

    permission_classes = []
    pagination_class = FeedPagination
    filter_backends = [OrderingFilter]
    ordering_fields = ['created_date', 'score', 'unified_document__hot_score', 'amount_raised']
    ordering = ['status_priority', '-created_date', 'id']

    def get_cache_key(self, request, feed_type=""):
        base_key = super().get_cache_key(request, feed_type)
        fundraise_status = request.query_params.get("fundraise_status", "")
        ordering = request.query_params.get("ordering", "")
        return f"{base_key}-{fundraise_status}:{ordering}"

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    def filter_queryset(self, queryset):
        """
        Override to ensure status_priority is always the primary sort field.
        This maintains OPEN items before CLOSED items regardless of secondary sort.
        """
        queryset = super().filter_queryset(queryset)
        
        # Get the ordering parameter
        ordering_param = self.request.query_params.get(self.ordering_param, '')
        
        # Handle special case for amount_raised (needs annotation)
        if 'amount_raised' in ordering_param:
            queryset = queryset.annotate(
                amount_raised=Coalesce(
                    Sum("unified_document__fundraises__escrow__amount_holding") +
                    Sum("unified_document__fundraises__escrow__amount_paid"),
                    0, output_field=DecimalField()
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

    def list(self, request, *args, **kwargs):
        from django.conf import settings
        
        page = request.query_params.get("page", "1")
        page_num = int(page)
        grant_id = request.query_params.get("grant_id", None)
        created_by = request.query_params.get("created_by", None)
        fundraise_status = request.query_params.get("fundraise_status", None)
        ordering = request.query_params.get("ordering", None)
        cache_key = self.get_cache_key(request, "funding")
        
        # Updated to match new OrderingFilter parameter format
        cacheable_orderings = {None, "-created_date", "-unified_document__hot_score", "-score", "-amount_raised"}
        cacheable_statuses = {None, "OPEN", "CLOSED"}
        
        use_cache = (
            page_num <= 4 and 
            grant_id is None and
            created_by is None and
            ordering in cacheable_orderings and
            (fundraise_status.upper() if fundraise_status else None) in cacheable_statuses
        )
        
        return self._list_fund_entries(request, cache_key, use_cache)

    def get_queryset(self):
        fundraise_status = self.request.query_params.get("fundraise_status", None)
        grant_id = self.request.query_params.get("grant_id", None)
        created_by = self.request.query_params.get("created_by", None)

        queryset = self._build_base_queryset(created_by)
        
        if grant_id:
            queryset = queryset.filter(grant_applications__grant_id=grant_id)
        
        if fundraise_status:
            status_upper = fundraise_status.upper()
            if status_upper == "CLOSED":
                queryset = queryset.filter(unified_document__fundraises__status=Fundraise.COMPLETED)
            
            # Annotate fundraise_end_date for status-specific ordering if needed
            queryset = queryset.annotate(
                fundraise_end_date=F("unified_document__fundraises__end_date")
            )
        
        return queryset

    @property
    def _fundraise_content_type(self):
        """Get ContentType for Fundraise model using mixin's helper pattern"""
        return self._get_content_type(Fundraise)
    
    def _build_base_queryset(self, created_by=None):
        now = timezone.now()
        
        # Subquery to check if post has any active (open and not expired) fundraises
        has_active = Fundraise.objects.filter(
            unified_document_id=OuterRef("unified_document_id"),
            status=Fundraise.OPEN
        ).filter(Q(end_date__isnull=True) | Q(end_date__gt=now)).values('pk')[:1]
        
        # Subquery to count unique contributors for each fundraise
        contributor_count_subquery = Purchase.objects.filter(
            content_type=self._fundraise_content_type,
            object_id=OuterRef("pk")
        ).values('object_id').annotate(
            count=Count('user_id', distinct=True)
        ).values('count')
        
        # Prefetch fundraises with related data to avoid N+1 queries
        fundraise_prefetch = Prefetch(
            "unified_document__fundraises",
            queryset=Fundraise.objects.select_related("escrow").prefetch_related(
                "nonprofit_links"
            ).annotate(
                contributor_count=Coalesce(
                    Subquery(contributor_count_subquery, output_field=IntegerField()),
                    0
                )
            ).order_by("end_date")
        )
        
        queryset = ResearchhubPost.objects.select_related(
            # Fetch post creator's user data in a single query to avoid N+1
            "created_by__author_profile__user",
            # Fetch unified document to avoid additional queries
            "unified_document"
        ).prefetch_related(
            # Fetch all hubs associated with the document
            "unified_document__hubs",
            # Fetch fundraises with escrow, nonprofit links, and contributor counts
            fundraise_prefetch
        ).filter(
            # Only show preregistration posts that haven't been removed
            document_type=PREREGISTRATION,
            unified_document__is_removed=False
        ).annotate(
            # Priority field: 0 for open/active fundraises, 1 for closed/expired
            # Used to sort open items before closed items
            status_priority=Case(
                When(Exists(has_active), then=Value(0)),
                default=Value(1),
                output_field=IntegerField()
            )
        )
        
        return queryset.filter(created_by__id=created_by) if created_by else queryset
