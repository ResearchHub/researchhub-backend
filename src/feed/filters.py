from typing import Any, List, Type, Union
from django.db.models import (
    Case,
    DateTimeField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    QuerySet,
    Subquery,
    Value,
    When,
)
from django.utils import timezone
from rest_framework.filters import OrderingFilter
from rest_framework.request import Request

from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.grant_model import Grant


class FundOrderingFilter(OrderingFilter):
    """Custom ordering filter for grants and fundraises with best sorting logic."""

    def filter_queryset(self, request: Request, queryset: QuerySet, view: Any) -> QuerySet:
        ordering = self.get_ordering(request, queryset, view)
        
        queryset = self._apply_include_ended_filter(request, queryset, view)
        
        if not ordering:
            model_class, open_status, closed_statuses = self._get_model_config(view)
            return self._apply_best_sorting(queryset, model_class, open_status, closed_statuses)
        
        return super().filter_queryset(request, queryset, view)
    
    def _get_model_config(self, view: Any) -> tuple[Union[Type[Grant], Type[Fundraise]], str, List[str]]:
        if getattr(view, 'is_grant_view', False):
            return Grant, Grant.OPEN, [Grant.CLOSED, Grant.COMPLETED]
        return Fundraise, Fundraise.OPEN, [Fundraise.CLOSED, Fundraise.COMPLETED]
    
    def _apply_include_ended_filter(self, request: Request, queryset: QuerySet, view: Any) -> QuerySet:
        # Kept the check in, just in case, for if the FUNDING is closed
        # we do not want to apply the include_ended filter
        fundraise_status_filter_value  = request.query_params.get('fundraise_status', '').upper()
        include_ended = request.query_params.get('include_ended', 'true').upper() == 'TRUE' or fundraise_status_filter_value  == 'CLOSED'
        if include_ended:
            return queryset
        
        model_class, open_status, _ = self._get_model_config(view)
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

