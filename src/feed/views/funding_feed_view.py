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
        - newest (default): Sort by creation date (newest first)
        - hot_score: Sort by trending score (most engaging content)
        - upvotes: Sort by score (most upvoted first)
        - amount_raised: Sort by amount raised (highest first)
    """

    permission_classes = []
    pagination_class = FeedPagination

    def get_cache_key(self, request, feed_type=""):
        base_key = super().get_cache_key(request, feed_type)
        params = [
            request.query_params.get("fundraise_status", ""),
            request.query_params.get("ordering", "")
        ]
        return f"{base_key}-{':'.join(params)}-v2"

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    def list(self, request, *args, **kwargs):
        page = request.query_params.get("page", "1")
        page_num = int(page)
        grant_id = request.query_params.get("grant_id", None)
        created_by = request.query_params.get("created_by", None)
        fundraise_status = request.query_params.get("fundraise_status", None)
        ordering = request.query_params.get("ordering", None)
        cache_key = self.get_cache_key(request, "funding")
        
        cacheable_orderings = {None, "hot_score", "upvotes", "amount_raised"}
        cacheable_statuses = {None, "OPEN", "CLOSED"}
        
        use_cache = (
            page_num <= 2 and
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
        ordering = self.request.query_params.get("ordering")
        
        if grant_id:
            queryset = queryset.filter(grant_applications__grant_id=grant_id)
        
        if fundraise_status:
            status_upper = fundraise_status.upper()
            if status_upper == "CLOSED":
                queryset = queryset.filter(unified_document__fundraises__status=Fundraise.COMPLETED)
        
        return self._apply_ordering(queryset, ordering, fundraise_status)

    _fundraise_content_type = None
    
    @classmethod
    def _get_fundraise_content_type(cls):
        if cls._fundraise_content_type is None:
            cls._fundraise_content_type = ContentType.objects.get_for_model(Fundraise)
        return cls._fundraise_content_type
    
    def _build_base_queryset(self, created_by=None):
        now = timezone.now()
        
        has_active = Fundraise.objects.filter(
            unified_document_id=OuterRef("unified_document_id"),
            status=Fundraise.OPEN
        ).filter(Q(end_date__isnull=True) | Q(end_date__gt=now))
        
        contributor_count_subquery = Purchase.objects.filter(
            content_type=self._get_fundraise_content_type(),
            object_id=OuterRef("pk")
        ).values('object_id').annotate(
            count=Count('user_id', distinct=True)
        ).values('count')
        
        fundraise_prefetch = Prefetch(
            "unified_document__fundraises",
            queryset=Fundraise.objects.select_related("escrow").annotate(
                contributor_count=Coalesce(
                    Subquery(contributor_count_subquery, output_field=IntegerField()),
                    0
                )
            ).order_by("end_date")
        )
        
        queryset = ResearchhubPost.objects.select_related(
            "created_by__author_profile__user", "unified_document"
        ).prefetch_related(
            "unified_document__hubs", fundraise_prefetch
        ).filter(
            document_type=PREREGISTRATION, unified_document__is_removed=False
        ).annotate(
            status_priority=Case(
                When(Exists(has_active), then=Value(0)),
                default=Value(1),
                output_field=IntegerField()
            )
        )
        
        return queryset.filter(created_by__id=created_by) if created_by else queryset

    def _apply_ordering(self, queryset, ordering, fundraise_status=None):
        if ordering == "amount_raised":
            return queryset.annotate(
                amount_raised=Coalesce(
                    Sum("unified_document__fundraises__escrow__amount_holding") +
                    Sum("unified_document__fundraises__escrow__amount_paid"),
                    0, output_field=DecimalField()
                )
            ).order_by("status_priority", "-amount_raised", "id")
        
        if ordering:
            order_fields = {
                "hot_score": ("status_priority", "-unified_document__hot_score", "id"),
                "upvotes": ("status_priority", "-score", "id"),
            }.get(ordering, ("status_priority", "-created_date", "id"))
            return queryset.order_by(*order_fields)
        
        if fundraise_status:
            status_upper = fundraise_status.upper()
            if status_upper == "OPEN":
                return queryset.annotate(
                    fundraise_end_date=F("unified_document__fundraises__end_date")
                ).order_by("status_priority", "fundraise_end_date", "id")
            elif status_upper == "CLOSED":
                return queryset.annotate(
                    fundraise_end_date=F("unified_document__fundraises__end_date")
                ).order_by("-fundraise_end_date", "id")
        
        return queryset.annotate(
            fundraise_end_date=F("unified_document__fundraises__end_date"),
            open_sort_date=Case(
                When(unified_document__fundraises__status=Fundraise.OPEN, 
                     then=F("fundraise_end_date")),
                default=Value(None),
                output_field=DateTimeField()
            ),
            closed_sort_date=Case(
                When(unified_document__fundraises__status=Fundraise.COMPLETED, 
                     then=F("fundraise_end_date")),
                default=Value(None),
                output_field=DateTimeField()
            )
        ).order_by("status_priority", "open_sort_date", "-closed_sort_date", "id")
