from django.db.models import (
    Case,
    Count,
    DateTimeField,
    DecimalField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce
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
        # Get the sort_by parameter from the request
        sort_by_param = request.query_params.get('sort_by', '')
        
        # Apply include_ended filtering BEFORE any ordering logic
        queryset = self._apply_include_ended_filter(request, queryset, view)
        
        # Check view type using an explicit attribute (defaults to fundraise view)
        if getattr(view, 'is_grant_view', False):
            model_class = Grant
            open_status = Grant.OPEN
            closed_statuses = [Grant.CLOSED, Grant.COMPLETED]
        else:
            model_class = Fundraise
            open_status = Fundraise.OPEN
            closed_statuses = [Fundraise.CLOSED, Fundraise.COMPLETED]
        
        # Handle different sorting options
        if not sort_by_param or sort_by_param == 'best':
            # Default "best" sorting
            return self._apply_best_sorting(
                queryset, model_class, open_status, closed_statuses
            )
        elif sort_by_param == 'upvotes':
            return self._apply_upvotes_sorting(queryset)
        elif sort_by_param == 'most_applicants':
            return self._apply_most_applicants_sorting(queryset, model_class)
        elif sort_by_param == 'amount_raised':
            return self._apply_amount_raised_sorting(queryset, model_class)
        
        # Fall back to default ordering behavior for any other sorting parameters
        return super().filter_queryset(request, queryset, view)
    
    def _apply_include_ended_filter(self, request, queryset, view):
        """
        Apply include_ended filtering to exclude OPEN items past their end_date.
        
        Args:
            request: The request object
            queryset: The queryset to filter
            view: The view instance
            
        Returns:
            Filtered queryset
        """
        # Check include_ended parameter - only apply if not on "Previously Funded" tab
        fundraise_status = request.query_params.get('fundraise_status', '').upper()
        is_previously_funded_tab = fundraise_status == 'CLOSED'
        
        include_ended = request.query_params.get('include_ended', 'true').lower() == 'true'
        # Don't apply include_ended filter on Previously Funded tab
        if is_previously_funded_tab:
            include_ended = True
        
        # Apply include_ended filtering
        if not include_ended:
            # Check view type to determine which model to filter
            if getattr(view, 'is_grant_view', False):
                model_class = Grant
                open_status = Grant.OPEN
            else:
                model_class = Fundraise
                open_status = Fundraise.OPEN
            
            # Exclude OPEN items that are past their end_date
            now = timezone.now()
            queryset = queryset.exclude(
                unified_document__in=model_class.objects.filter(
                    status=open_status,
                    end_date__lt=now
                ).values_list('unified_document_id', flat=True)
            )
        
        return queryset
    
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
    
    def _apply_upvotes_sorting(self, queryset):
        """
        Apply upvotes sorting for grants or fundraises.
        Sorts by document filter upvoted_all field (descending).
        
        Args:
            queryset: The queryset to sort
        """
        return queryset.annotate(
            upvotes=Coalesce(
                F("unified_document__document_filter__upvoted_all"), 
                0
            )
        ).order_by("-upvotes", "-created_date")
    
    def _apply_most_applicants_sorting(self, queryset, model_class):
        """
        Apply most applicants sorting for grants or fundraises.
        For grants: sorts by number of applications (descending)
        For fundraises: sorts by number of contributors (descending)
        
        Args:
            queryset: The queryset to sort
            model_class: Grant or Fundraise model
        """
        if model_class == Grant:
            # For grants, count applications
            return queryset.annotate(
                application_count=Count(
                    "unified_document__grants__applications",
                    distinct=True
                )
            ).order_by("-application_count", "-created_date")
        else:
            # For fundraises, count contributors (purchases)
            return queryset.annotate(
                contributor_count=Count(
                    "unified_document__fundraises__purchases__user",
                    distinct=True
                )
            ).order_by("-contributor_count", "-created_date")
    
    def _apply_amount_raised_sorting(self, queryset, model_class):
        """
        Apply amount raised sorting for grants or fundraises.
        For grants: sorts by grant amount (descending)
        For fundraises: sorts by amount raised from escrow (descending)
        
        Args:
            queryset: The queryset to sort
            model_class: Grant or Fundraise model
        """
        if model_class == Grant:
            # For grants, sort by the grant amount
            return queryset.annotate(
                amount_value=Coalesce(
                    F("unified_document__grants__amount"), 
                    0,
                    output_field=DecimalField(max_digits=19, decimal_places=2)
                )
            ).order_by("-amount_value", "-created_date")
        else:
            # For fundraises, sort by amount raised (escrow amount_holding + amount_paid)
            return queryset.annotate(
                amount_raised=Coalesce(
                    F("unified_document__fundraises__escrow__amount_holding") + 
                    F("unified_document__fundraises__escrow__amount_paid"),
                    0,
                    output_field=DecimalField(max_digits=19, decimal_places=10)
                )
            ).order_by("-amount_raised", "-created_date")

