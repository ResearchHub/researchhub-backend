from typing import Any, List, Type, Union
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
    Value,
    When,
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
        # Get the sort_by parameter from the request
        sort_by_param = request.query_params.get('sort_by', '') 
        model_class, open_status, closed_statuses = self._get_model_config(view)
        queryset = self._apply_include_ended_filter(request, queryset, view, model_class, open_status) 
        if sort_by_param == 'upvotes':
            return self._apply_upvotes_sorting(queryset)
        elif sort_by_param == 'most_applicants': 
            return self._apply_most_applicants_sorting(queryset, model_class)
        elif sort_by_param == 'amount_raised': 
            return self._apply_amount_raised_sorting(queryset, model_class)
        else:
            # Default to "best" sorting for empty, 'best', or any other value
            return self._apply_best_sorting(queryset, model_class, open_status, closed_statuses)
    
    def _get_model_config(self, view: Any) -> tuple[Union[Type[Grant], Type[Fundraise]], str, List[str]]:
        if getattr(view, 'is_grant_view', False):
            return Grant, Grant.OPEN, [Grant.CLOSED, Grant.COMPLETED]
        return Fundraise, Fundraise.OPEN, [Fundraise.CLOSED, Fundraise.COMPLETED]
    
    def _apply_include_ended_filter(self, request: Request, queryset: QuerySet, view: Any, model_class: Union[Type[Grant], Type[Fundraise]], open_status: str) -> QuerySet:
        # Kept the check in, just in case, for if the FUNDING is closed
        # we do not want to apply the include_ended filter
        fundraise_status = request.query_params.get('fundraise_status', '').upper()
        is_closed_funding = fundraise_status == 'CLOSED'
        include_ended = request.query_params.get('include_ended', 'true').lower() == 'true'
        if is_closed_funding:
            include_ended = True
        if include_ended:
            return queryset 
        now = timezone.now()
        return queryset.exclude(
            unified_document__in=model_class.objects.filter(
                status=open_status,
                end_date__lt=now
            ).values_list('unified_document_id', flat=True)
        )
    
    def _apply_best_sorting(self, queryset: QuerySet, model_class: Union[Type[Grant], Type[Fundraise]], 
                           open_status: str, closed_statuses: List[str]) -> QuerySet:
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
    
    def _apply_upvotes_sorting(self, queryset: QuerySet) -> QuerySet:
        return queryset.annotate(
            upvotes=Coalesce(
                F("unified_document__document_filter__upvoted_all"), 
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
    
    def _apply_amount_raised_sorting(self, queryset: QuerySet, model_class: Union[Type[Grant], Type[Fundraise]]) -> QuerySet:
        if model_class == Grant:
            return queryset.annotate(
                amount_value=Coalesce(
                    F("unified_document__grants__amount"), 
                    0,
                    output_field=DecimalField(max_digits=19, decimal_places=2)
                )
            ).order_by("-amount_value", "-created_date")
        else:
            return queryset.annotate(
                amount_raised=Coalesce(
                    F("unified_document__fundraises__escrow__amount_holding") + 
                    F("unified_document__fundraises__escrow__amount_paid"),
                    0,
                    output_field=DecimalField(max_digits=19, decimal_places=10)
                )
            ).order_by("-amount_raised", "-created_date")

