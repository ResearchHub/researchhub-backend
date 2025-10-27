from django.db.models import (
    Case,
    DateTimeField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Subquery,
    Value,
    When,
)
from django.utils import timezone
from rest_framework.filters import OrderingFilter

from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.grant_model import Grant


class FundOrderingFilter(OrderingFilter):
    """
    Custom ordering filter for grants and fundraises.
    
    When no ordering parameter is provided (default "best" behavior):
    - OPEN + Active (not expired) items first, sorted by soonest deadline
    - OPEN + Expired items next, sorted by soonest deadline
    - CLOSED/COMPLETED items last, sorted by most recent deadline
    
    Falls back to standard OrderingFilter for other ordering options.
    """

    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)
        
        # If no ordering parameter specified, apply "best" sorting
        if not ordering:
            # Check view type using an explicit attribute (defaults to fundraise view)
            if getattr(view, 'is_grant_view', False):
                model_class = Grant
                open_status = Grant.OPEN
                closed_statuses = [Grant.CLOSED, Grant.COMPLETED]
            else:
                model_class = Fundraise
                open_status = Fundraise.OPEN
                closed_statuses = [Fundraise.CLOSED, Fundraise.COMPLETED]
            
            return self._apply_best_sorting(
                queryset, model_class, open_status, closed_statuses
            )
        
        # Fall back to default ordering behavior for any explicit ordering parameters
        return super().filter_queryset(request, queryset, view)
    
    def _apply_best_sorting(self, queryset, model_class, open_status, closed_statuses):
        """
        Apply best sorting logic for grants or fundraises.
        
        Args:
            queryset: The queryset to sort
            model_class: Grant or Fundraise model
            open_status: The OPEN status value for the model
            closed_statuses: List of CLOSED/COMPLETED status values
        """
        now = timezone.now()
        
        # Check if there's any OPEN item (for items with no end_date)
        has_open_item = Exists(
            model_class.objects.filter(
                unified_document_id=OuterRef("unified_document_id"),
                status=open_status
            )
        )
        
        # Get earliest end_date from OPEN items
        earliest_open_end_date = model_class.objects.filter(
            unified_document_id=OuterRef("unified_document_id"),
            status=open_status
        ).values("end_date").order_by("end_date")[:1]
        
        # Get latest end_date from CLOSED/COMPLETED items
        latest_closed_end_date = model_class.objects.filter(
            unified_document_id=OuterRef("unified_document_id"),
            status__in=closed_statuses
        ).values("end_date").order_by("-end_date")[:1]
        
        queryset = queryset.annotate(
            has_open=has_open_item,
            earliest_open_end_date=Subquery(earliest_open_end_date, output_field=DateTimeField()),
            latest_closed_end_date=Subquery(latest_closed_end_date, output_field=DateTimeField()),
            sort_option=Case(
                # 0: OPEN + Active (end_date >= now or no end_date)
                When(has_open=True, earliest_open_end_date__gte=now, then=Value(0)),
                When(has_open=True, earliest_open_end_date__isnull=True, then=Value(0)),
                # 1: OPEN + Expired (end_date < now)
                When(has_open=True, earliest_open_end_date__lt=now, then=Value(1)),
                # 2: CLOSED/COMPLETED (no open items)
                default=Value(2),
                output_field=IntegerField(),
            ),
            # For active items, use ascending (soonest first)
            # For expired/closed, we'll sort descending (most recent first)
            sort_date_active=Case(
                When(sort_option=0, then=F("earliest_open_end_date")),
                default=None,
                output_field=DateTimeField(),
            ),
            sort_date_expired_or_closed=Case(
                When(sort_option=1, then=F("earliest_open_end_date")),
                When(sort_option=2, then=F("latest_closed_end_date")),
                default=None,
                output_field=DateTimeField(),
            ),
        )
        
        return queryset.order_by(
            "sort_option",
            F("sort_date_active").asc(nulls_last=True),
            F("sort_date_expired_or_closed").desc(nulls_last=True),
            "-created_date"
        )

