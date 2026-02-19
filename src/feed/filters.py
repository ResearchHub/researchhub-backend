from typing import Any, Type, Union
from django.db.models import (
    Case,
    Count,
    DateTimeField,
    DecimalField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
    Q,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.filters import OrderingFilter
from rest_framework.request import Request

from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.grant_model import Grant


class FundOrderingFilter(OrderingFilter):
    """Custom ordering filter for grants and fundraises with best sorting logic."""
    

    def filter_queryset(self, request: Request, queryset: QuerySet, view: Any) -> QuerySet:
        """Apply filtering and sorting to the queryset."""
        model_config = self._get_model_config(view)
        queryset = self._apply_include_ended_filter(request, queryset, view, model_config)
        return self._apply_custom_sorting(queryset, model_config, request, view)
     
    def _get_model_config(self, view: Any) -> dict[str, Union[Type[Grant], Type[Fundraise], str]]:
        if getattr(view, 'is_grant_view', False):
            return {
                'model_class': Grant,
                'open_status': Grant.OPEN,
                'closed_status': Grant.CLOSED,
                'completed_status': Grant.COMPLETED
            }
        return {
            'model_class': Fundraise,
            'open_status': Fundraise.OPEN,
            'closed_status': Fundraise.CLOSED,
            'completed_status': Fundraise.COMPLETED
        }
    
    def _apply_include_ended_filter(self, request: Request, queryset: QuerySet, view: Any, model_config: dict[str, Union[Type[Grant], Type[Fundraise], str]]) -> QuerySet:
        fundraise_status_filter_value = request.query_params.get('fundraise_status', '').upper()
        include_ended_filter_value = request.query_params.get('include_ended', 'true').upper()
        should_apply_filter = include_ended_filter_value == 'TRUE' or fundraise_status_filter_value == 'CLOSED'
        if should_apply_filter:
            return queryset
        
        model_class = model_config['model_class']
        open_status = model_config['open_status']
        now = timezone.now()
        return queryset.exclude(
            unified_document__in=model_class.objects.filter(
                status=open_status,
                end_date__lt=now
            ).values_list('unified_document_id', flat=True)
        )

    def _apply_custom_sorting(self, queryset: QuerySet, model_config: dict, request: Request, view: Any) -> QuerySet:
        """Apply custom sorting based on order value."""
        ordering_list = self.get_ordering(request, queryset, view)
        ordering = ordering_list[0].lstrip('-') if ordering_list else 'newest'
        grant_id = request.query_params.get('grant_id')
 
        if ordering == 'newest':
            return self._apply_newest_sorting(queryset, model_config)
        elif ordering == 'best':
            # For RFP applications (when grant_id is passed), sort by most funded
            if grant_id:
                return self._apply_amount_raised_sorting(queryset, Fundraise)
            return self._apply_best_sorting(queryset, model_config)
        elif ordering == 'upvotes':
            return self._apply_upvotes_sorting(queryset)
        elif ordering == 'most_applicants':
            return self._apply_most_applicants_sorting(queryset, model_config['model_class'])
        elif ordering == 'amount_raised':
            return self._apply_amount_raised_sorting(queryset, model_config['model_class'])
        elif ordering == 'leaderboard':
            return self._apply_leaderboard_sorting(queryset)
        else:
            # For any other ordering field, fall back to DRF's standard ordering
            return super().filter_queryset(request, queryset, view)
            
    def get_ordering(self, request: Request, queryset: QuerySet, view: Any):
        """Get ordering from request with DRF-compatible signature."""
        ordering_param = request.query_params.get(self.ordering_param, '')
        
        # Determine default ordering based on view type
        is_grant_view = getattr(view, 'is_grant_view', False)
        default_ordering = 'newest' if is_grant_view else 'best'
        
        if ordering_param:
            fields = [field.strip() for field in ordering_param.split(',')]
            if fields:
                field = fields[0]
                field_name = field.lstrip('-') 
                custom_fields = ['newest', 'best', 'upvotes', 'most_applicants', 'amount_raised', 'leaderboard']
                if field_name in custom_fields:
                    return [field] 
                ordering_fields = getattr(view, 'ordering_fields', None)
                if ordering_fields and field_name in ordering_fields:
                    return [field] 
                return [default_ordering] 
        return [default_ordering] 

    def _apply_newest_sorting(self, queryset: QuerySet, model_config: dict[str, Union[Type[Grant], Type[Fundraise], str]]) -> QuerySet:
        model_class = model_config['model_class']
        open_status = model_config['open_status']
        closed_statuses = [model_config['closed_status'], model_config['completed_status']]
        
        now = timezone.now()
        
        has_open_item = Exists(
            model_class.objects.filter(
                unified_document_id=OuterRef("unified_document_id"),
                status=open_status
            )
        )
        
        earliest_open_end_date = model_class.objects.filter(
            unified_document_id=OuterRef("unified_document_id"),
            status=open_status
        ).values("end_date").order_by("end_date")[:1]
        
        latest_closed_end_date = model_class.objects.filter(
            unified_document_id=OuterRef("unified_document_id"),
            status__in=closed_statuses
        ).values("end_date").order_by("-end_date")[:1]
        
        queryset = queryset.annotate(
            has_open=has_open_item,
            earliest_open_end_date=Subquery(earliest_open_end_date, output_field=DateTimeField()),
            latest_closed_end_date=Subquery(latest_closed_end_date, output_field=DateTimeField()),
            sort_option=Case(
                When(has_open=True, earliest_open_end_date__gte=now, then=Value(0)),
                When(has_open=True, earliest_open_end_date__isnull=True, then=Value(0)),
                When(has_open=True, earliest_open_end_date__lt=now, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            ),
        )
        
        return queryset.order_by("sort_option", "-created_date")

    def _apply_best_sorting(self, queryset: QuerySet, model_config: dict[str, Union[Type[Grant], Type[Fundraise], str]]) -> QuerySet:
        """
        Sort by best with conditional logic (for fundraises/proposals only):
        - Active open items: sort by amount raised (desc), then created date (desc)
        - Expired open items: sort by created date (desc) only
        - Closed items: sort by created date (desc) only
        """ 
        open_status = Fundraise.OPEN
        now = timezone.now()
        
        amount_expr = Coalesce(
            Sum(
                F('unified_document__fundraises__escrow__amount_holding') + 
                F('unified_document__fundraises__escrow__amount_paid'),
                filter=Q(unified_document__fundraises__status=open_status)
            ),
            Value(0),
            output_field=DecimalField(max_digits=19, decimal_places=10)
        )
        
        has_open_item = Exists(
            Fundraise.objects.filter(
                unified_document_id=OuterRef("unified_document_id"),
                status=open_status
            )
        )
        
        earliest_open_end_date = Fundraise.objects.filter(
            unified_document_id=OuterRef("unified_document_id"),
            status=open_status
        ).values("end_date").order_by("end_date")[:1]
        
        queryset = queryset.annotate(
            has_open=has_open_item,
            earliest_open_end_date=Subquery(earliest_open_end_date, output_field=DateTimeField()),
            sort_option=Case(
                When(has_open=True, earliest_open_end_date__gte=now, then=Value(0)),  # Active
                When(has_open=True, earliest_open_end_date__isnull=True, then=Value(0)),  # Active (no end date)
                When(has_open=True, earliest_open_end_date__lt=now, then=Value(1)),  # Expired
                default=Value(2),  # Closed
                output_field=IntegerField(),
            ),
        )
        
        queryset = queryset.annotate(
            amount=Case(
                When(sort_option=0, then=amount_expr),  # Only active items sorted by amount
                default=Value(0),
                output_field=DecimalField(max_digits=19, decimal_places=10),
            ),
        )
        
        return queryset.order_by('sort_option', '-amount', '-created_date')
    
    def _apply_upvotes_sorting(self, queryset: QuerySet) -> QuerySet:
        """Use document_filter upvotes if available, otherwise fallback to post score"""
        return queryset.annotate(
            upvotes=Coalesce(
                F("unified_document__document_filter__upvoted_all"),
                F("score"),
                0
            )
        ).order_by("-upvotes", "-created_date")
    
    def _apply_most_applicants_sorting(self, queryset: QuerySet, model_class: Union[Type[Grant], Type[Fundraise]]) -> QuerySet:
        if model_class == Grant:
            return queryset.annotate(
                application_count=Count(
                    "unified_document__grants__applications",
                    distinct=True
                )
            ).order_by("-application_count", "-created_date")
        else:
            return queryset.annotate(
                contributor_count=Count(
                    "unified_document__fundraises__purchases__user",
                    distinct=True
                )
            ).order_by("-contributor_count", "-created_date")
    
    def _apply_leaderboard_sorting(self, queryset: QuerySet) -> QuerySet:
        """Return top OPEN grants sorted by total contributions to their proposals."""
        leaderboard_size = 5
        now = timezone.now()

        queryset = queryset.filter(
            Q(unified_document__grants__status=Grant.OPEN),
            Q(unified_document__grants__end_date__isnull=True)
            | Q(unified_document__grants__end_date__gt=now),
        )

        # Build the ORM path: grant post → grant → applications → proposal → fundraise → escrow
        grant = "unified_document__grants"
        proposals = f"{grant}__applications__preregistration_post"
        fundraises = f"{proposals}__unified_document__fundraises"
        escrow = f"{fundraises}__escrow"

        queryset = queryset.annotate(
            total_funded=Coalesce(
                Sum(F(f"{escrow}__amount_holding") + F(f"{escrow}__amount_paid")),
                Value(0),
                output_field=DecimalField(max_digits=19, decimal_places=10),
            ),
            grant_amount=Coalesce(
                Sum(
                    F("unified_document__grants__amount"),
                    output_field=DecimalField(max_digits=19, decimal_places=2),
                ),
                Value(0),
                output_field=DecimalField(max_digits=19, decimal_places=2),
            ),
        )

        return queryset.order_by("-total_funded", "-grant_amount")[:leaderboard_size]

    def _apply_amount_raised_sorting(self, queryset: QuerySet, model_class: Union[Type[Grant], Type[Fundraise]]) -> QuerySet:
        if model_class == Grant:
            return queryset.annotate(
                amount_value=Coalesce(
                    Sum(
                        F("unified_document__grants__amount"),
                        output_field=DecimalField(max_digits=19, decimal_places=2)
                    ),
                    0,
                    output_field=DecimalField(max_digits=19, decimal_places=2)
                )
            ).order_by("-amount_value", "-created_date")
        else:
            return queryset.annotate(
                amount_raised=Coalesce(
                    Sum(
                        F("unified_document__fundraises__escrow__amount_holding") + 
                        F("unified_document__fundraises__escrow__amount_paid"),
                        output_field=DecimalField(max_digits=19, decimal_places=10)
                    ),
                    0,
                    output_field=DecimalField(max_digits=19, decimal_places=10)
                )
            ).order_by("-amount_raised", "-created_date")

