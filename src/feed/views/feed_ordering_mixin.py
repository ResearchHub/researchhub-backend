"""
Shared ordering logic for funding and grant feeds.
Provides consistent sorting with status priority (OPEN before CLOSED).
"""
from django.db.models import Case, DecimalField, F, Sum, Value, When
from django.db.models.functions import Coalesce

from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.grant_model import Grant


class FeedOrderingMixin:
    """Mixin to provide consistent ordering across funding and grant feeds."""
    
    def _apply_status_priority_ordering(self, queryset, status_field, *order_fields):
        """
        Apply status-priority ordering: OPEN items first, then CLOSED/COMPLETED.
        
        Args:
            queryset: The queryset to order
            status_field: The field path to the status (e.g., 'unified_document__fundraises__status')
            *order_fields: Additional fields to order by after status
        """
        open_status = self._get_open_status()
        return queryset.order_by(
            Case(
                When(**{status_field: open_status}, then=Value(0)),
                default=Value(1),
            ),
            *order_fields,
            'id'  # Final tie-breaker for consistent ordering
        )
    
    def _order_by_amount_raised(self, queryset, status_field):
        """Order by amount raised with status priority."""
        queryset = queryset.annotate(
            amount_raised=Coalesce(
                Sum("unified_document__fundraises__escrow__amount_holding") +
                Sum("unified_document__fundraises__escrow__amount_paid"),
                0,
                output_field=DecimalField(),
            )
        )
        return self._apply_status_priority_ordering(queryset, status_field, "-amount_raised")
    
    def apply_ordering(self, queryset, ordering, status_field):
        """
        Apply ordering to queryset based on the ordering parameter.
        
        Args:
            queryset: The queryset to order
            ordering: The ordering type ('hot_score', 'upvotes', 'amount_raised')
            status_field: Field path to status (e.g., 'unified_document__fundraises__status')
        """
        if ordering == "hot_score":
            return self._apply_status_priority_ordering(
                queryset, status_field, "-unified_document__hot_score"
            )
        elif ordering == "upvotes":
            return self._apply_status_priority_ordering(queryset, status_field, "-score")
        elif ordering == "amount_raised":
            return self._order_by_amount_raised(queryset, status_field)
        else:  # newest (default when ordering is None or "")
            return self._apply_status_priority_ordering(queryset, status_field, "-created_date")
    
    def _get_open_status(self):
        """Override in subclass to return the OPEN status constant."""
        raise NotImplementedError("Subclass must implement _get_open_status()")

