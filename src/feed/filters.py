from typing import Any, Type, Union
from django.db.models import (
    Case,
    Count,
    DateTimeField,
    DecimalField,
    Exists,
    F,
    IntegerField,
    Max,
    OuterRef,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.filters import OrderingFilter
from rest_framework.request import Request

from feed.fund_best_score import calculate_fund_best_score_annotations
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.grant_model import Grant


class FundOrderingFilter(OrderingFilter):
    """Custom ordering filter for grants and fundraises with best sorting logic."""
    

    def filter_queryset(self, request: Request, queryset: QuerySet, view: Any) -> QuerySet:
        """Apply filtering and sorting to the queryset."""
        model_config = self._get_model_config(view)
        queryset = self._apply_status_filter(request, queryset, view, model_config)
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
    
    def _apply_status_filter(self, request: Request, queryset: QuerySet, view: Any, model_config: dict[str, Union[type[Grant], type[Fundraise], str]]) -> QuerySet:
        """Filter grants/fundraises based on ordering parameter."""
        import logging
        logger = logging.getLogger(__name__)
        
        ordering_param = request.query_params.get(self.ordering_param, '')
        ordering = ordering_param.lstrip('-') if ordering_param else 'newest'
        
        model_class = model_config['model_class']
        open_status = model_config['open_status']
        closed_statuses = [model_config['closed_status'], model_config['completed_status']]
        now = timezone.now()
        
        logger.info(f"STATUS FILTER - ordering: {ordering}, model: {model_class.__name__}")
        
        if ordering == 'ended':
            if model_class == Grant:
                # For Grants: "ended" means OPEN but expired (past end_date)
                logger.info(f"Filtering for ENDED Grants (OPEN but past end_date)")
                ended_ids = list(
                    Grant.objects.filter(
                        status=open_status,
                        end_date__lt=now
                    ).values_list('unified_document_id', flat=True)
                )
            else:
                # For Fundraises: "ended" means CLOSED or COMPLETED only
                # EXCLUDE any docs that have ANY OPEN fundraises
                logger.info(f"Filtering for ENDED Fundraises (CLOSED or COMPLETED only)")
                from django.db.models import Q
                # Find docs where ALL fundraises are closed/completed (none are OPEN)
                # Get docs that have at least one closed/completed
                has_closed = set(Fundraise.objects.filter(status__in=closed_statuses).values_list('unified_document_id', flat=True))
                # Get docs that have any OPEN fundraises  
                has_open = set(Fundraise.objects.filter(status=open_status).values_list('unified_document_id', flat=True))
                # Only show docs with closed fundraises that DON'T have any open ones
                ended_ids = list(has_closed - has_open)
                logger.info(f"Has closed: {len(has_closed)}, Has open: {len(has_open)}, Truly ended: {len(ended_ids)}, IDs: {ended_ids[:5]}")
            logger.info(f"Found {len(ended_ids)} unified_doc_ids with ENDED {model_class.__name__}: {ended_ids[:5]}")
            return queryset.filter(unified_document_id__in=ended_ids)
        else:
            if model_class == Grant:
                # For Grants: "active" means OPEN and (future end_date or no end_date)
                logger.info(f"Filtering for ACTIVE Grants (OPEN and not expired)")
                from django.db.models import Q
                active_ids = list(
                    Grant.objects.filter(
                        Q(status=open_status) & (Q(end_date__gte=now) | Q(end_date__isnull=True))
                    ).values_list('unified_document_id', flat=True)
                )
            else:
                # For Fundraises: "active" means OPEN status (including expired OPEN ones)
                logger.info(f"Filtering for ACTIVE Fundraises (OPEN, including expired)")
                active_ids = list(
                    Fundraise.objects.filter(
                        status=open_status
                    ).values_list('unified_document_id', flat=True)
                )
            logger.info(f"Found {len(active_ids)} unified_doc_ids with ACTIVE {model_class.__name__}: {active_ids[:5]}")
            return queryset.filter(unified_document_id__in=active_ids)

    def _apply_custom_sorting(self, queryset: QuerySet, model_config: dict, request: Request, view: Any) -> QuerySet:
        """Apply custom sorting based on order value."""
        ordering_list = self.get_ordering(request, queryset, view)
        ordering = ordering_list[0].lstrip('-') if ordering_list else 'newest'
 
        if ordering == 'newest':
            return self._apply_newest_sorting(queryset, model_config)
        elif ordering == 'best':
            return self._apply_best_sorting(queryset, model_config)
        elif ordering == 'ended':
            return self._apply_ended_sorting(queryset, model_config)
        elif ordering == 'upvotes':
            return self._apply_upvotes_sorting(queryset)
        elif ordering == 'most_applicants':
            return self._apply_most_applicants_sorting(queryset, model_config['model_class'])
        elif ordering == 'amount_raised':
            return self._apply_amount_raised_sorting(queryset, model_config['model_class'])
        else:
            # For any other ordering field, fall back to DRF's standard ordering
            return super().filter_queryset(request, queryset, view)
            
    def get_ordering(self, request: Request, queryset: QuerySet, view: Any):
        """Get ordering from request with DRF-compatible signature."""
        ordering_param = request.query_params.get(self.ordering_param, '')
        
        if ordering_param:
            fields = [field.strip() for field in ordering_param.split(',')]
            if fields:
                field = fields[0]
                field_name = field.lstrip('-') 
                custom_fields = ['newest', 'best', 'ended', 'upvotes', 'most_applicants', 'amount_raised']
                if field_name in custom_fields:
                    return [field] 
                ordering_fields = getattr(view, 'ordering_fields', None)
                if ordering_fields and field_name in ordering_fields:
                    return [field] 
                return ['newest'] 
        return ['newest'] 

    def _apply_newest_sorting(self, queryset: QuerySet, model_config: dict[str, Union[Type[Grant], Type[Fundraise], str]]) -> QuerySet:
        """
        Sort by priority: active (upcoming deadline first), then expired, then closed.
        NOTE: This only runs on OPEN items (closed items filtered out by _apply_status_filter).
        """
        model_class = model_config['model_class']
        open_status = model_config['open_status']
        now = timezone.now()
        
        # Get earliest end_date from OPEN grants/fundraises
        earliest_open_end_date = model_class.objects.filter(
            unified_document_id=OuterRef("unified_document_id"),
            status=open_status
        ).values("end_date").order_by("end_date")[:1]
        
        queryset = queryset.annotate(
            earliest_open_end_date=Subquery(earliest_open_end_date, output_field=DateTimeField()),
            # Categorize: 0=active (future deadline), 1=expired (past deadline but still OPEN)
            is_expired=Case(
                When(earliest_open_end_date__lt=now, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
        )
        
        # Sort: active items first (by closest deadline), then expired items (by most recent expiry)
        return queryset.order_by(
            "is_expired",
            F("earliest_open_end_date").asc(nulls_last=True),
            "-created_date"
        ).distinct()

    def _apply_best_sorting(self, queryset: QuerySet, model_config: dict[str, Union[Type[Grant], Type[Fundraise], str]]) -> QuerySet:
        """Sort by composite 'best' score using the fund_best_score module."""
        model_class = model_config['model_class']
        queryset = calculate_fund_best_score_annotations(queryset, model_class)
        return queryset.order_by('-best_score', '-created_date').distinct()
    
    def _apply_ended_sorting(self, queryset: QuerySet, model_config: dict[str, Union[Type[Grant], Type[Fundraise], str]]) -> QuerySet:
        """Sort ended (closed/completed) grants/fundraises by most recently closed."""
        model_class = model_config['model_class']
        
        if model_class == Grant:
            relation_path = 'unified_document__grants'
        else:
            relation_path = 'unified_document__fundraises'
        
        return queryset.annotate(
            latest_end_date=Max(F(f'{relation_path}__end_date'))
        ).order_by(
            F('latest_end_date').desc(nulls_last=True),
            '-created_date'
        ).distinct()
    
    def _apply_upvotes_sorting(self, queryset: QuerySet) -> QuerySet:
        return queryset.annotate(
            upvotes=Coalesce(
                F("unified_document__document_filter__upvoted_all"), 
                0
            )
        ).order_by("-upvotes", "-created_date").distinct()
    
    def _apply_most_applicants_sorting(self, queryset: QuerySet, model_class: Union[Type[Grant], Type[Fundraise]]) -> QuerySet:
        if model_class == Grant:
            return queryset.annotate(
                application_count=Count(
                    "unified_document__grants__applications",
                    distinct=True
                )
            ).order_by("-application_count", "-created_date").distinct()
        else:
            return queryset.annotate(
                contributor_count=Count(
                    "unified_document__fundraises__purchases__user",
                    distinct=True
                )
            ).order_by("-contributor_count", "-created_date").distinct()
    
    def _apply_amount_raised_sorting(self, queryset: QuerySet, model_class: Union[Type[Grant], Type[Fundraise]]) -> QuerySet:
        if model_class == Grant:
            # Aggregate total amount across all grants for each post
            return queryset.annotate(
                amount_value=Coalesce(
                    Sum(
                        F("unified_document__grants__amount"),
                        output_field=DecimalField(max_digits=19, decimal_places=2)
                    ),
                    0,
                    output_field=DecimalField(max_digits=19, decimal_places=2)
                )
            ).order_by("-amount_value", "-created_date").distinct()
        else:
            # Aggregate total amount raised across all fundraises for each post
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
            ).order_by("-amount_raised", "-created_date").distinct()

