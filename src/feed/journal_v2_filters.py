from typing import Any

from django.db.models import (
    Case,
    Count,
    DateTimeField,
    DecimalField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
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

from purchase.models import Fundraise

PROPOSAL_DOCUMENT_LOOKUP = "journey__preregistration_post__unified_document"
PROPOSAL_DOCUMENT_ID_OUTER_REF = (
    "journey__preregistration_post__unified_document_id"
)
PROPOSAL_FUNDRAISE_LOOKUP = f"{PROPOSAL_DOCUMENT_LOOKUP}__fundraises"


class JournalV2OrderingFilter(OrderingFilter):
    """Ordering filter for latest-stage cards in the post-based journal feed."""

    def filter_queryset(
        self, request: Request, queryset: QuerySet, view: Any
    ) -> QuerySet:
        """Apply journal v2 ordering to latest-stage journey cards."""
        ordering = self.get_ordering(request, queryset, view)[0].lstrip("-")

        if ordering == "newest":
            return self.sort_by_newest(queryset)
        if ordering == "best":
            return self.sort_by_best(queryset)
        if ordering == "upvotes":
            return self.sort_by_upvotes(queryset)
        if ordering == "most_applicants":
            return self.sort_by_most_applicants(queryset)
        if ordering == "amount_raised":
            return self.sort_by_amount_raised(queryset)

        return super().filter_queryset(request, queryset, view)

    def get_ordering(
        self, request: Request, queryset: QuerySet, view: Any
    ) -> list[str]:
        """Return the requested journal ordering or the view default."""
        ordering_param = request.query_params.get(self.ordering_param, "")
        default_ordering = getattr(view, "ordering", "best")

        if not ordering_param:
            return [default_ordering]

        fields = [field.strip() for field in ordering_param.split(",")]
        field = fields[0] if fields else default_ordering
        field_name = field.lstrip("-")
        ordering_fields = getattr(view, "ordering_fields", [])

        if field_name in ordering_fields:
            return [field]
        return [default_ordering]

    def sort_by_newest(self, queryset: QuerySet) -> QuerySet:
        """Sort journal cards with active proposals first, then newest cards."""
        now = timezone.now()

        return (
            queryset.annotate(
                has_open=self.build_open_fundraise_exists(),
                earliest_open_end_date=self.build_earliest_open_end_date_subquery(),
                sort_option=Case(
                    When(
                        has_open=True,
                        earliest_open_end_date__gte=now,
                        then=Value(0),
                    ),
                    When(
                        has_open=True,
                        earliest_open_end_date__isnull=True,
                        then=Value(0),
                    ),
                    When(
                        has_open=True,
                        earliest_open_end_date__lt=now,
                        then=Value(1),
                    ),
                    default=Value(2),
                    output_field=IntegerField(),
                ),
            )
            .order_by("sort_option", "-created_date", "-id")
        )

    def sort_by_best(self, queryset: QuerySet) -> QuerySet:
        """Sort active proposal fundraises by amount raised, then newest cards."""
        now = timezone.now()
        amount_raised = self.build_amount_raised_expression(
            filter=Q(**{f"{PROPOSAL_FUNDRAISE_LOOKUP}__status": Fundraise.OPEN})
        )

        return (
            queryset.annotate(
                has_open=self.build_open_fundraise_exists(),
                earliest_open_end_date=self.build_earliest_open_end_date_subquery(),
                sort_option=Case(
                    When(
                        has_open=True,
                        earliest_open_end_date__gte=now,
                        then=Value(0),
                    ),
                    When(
                        has_open=True,
                        earliest_open_end_date__isnull=True,
                        then=Value(0),
                    ),
                    When(
                        has_open=True,
                        earliest_open_end_date__lt=now,
                        then=Value(1),
                    ),
                    default=Value(2),
                    output_field=IntegerField(),
                ),
            )
            .annotate(
                amount=Case(
                    When(sort_option=0, then=amount_raised),
                    default=Value(0),
                    output_field=DecimalField(max_digits=19, decimal_places=10),
                )
            )
            .order_by("sort_option", "-amount", "-created_date", "-id")
        )

    def sort_by_upvotes(self, queryset: QuerySet) -> QuerySet:
        """Sort journal cards by their visible latest-stage upvotes."""
        return queryset.annotate(
            upvotes=Coalesce(
                F("unified_document__document_filter__upvoted_all"), F("score"), 0
            )
        ).order_by("-upvotes", "-created_date", "-id")

    def sort_by_most_applicants(self, queryset: QuerySet) -> QuerySet:
        """Sort journal cards by the proposal fundraise contributor count."""
        return queryset.annotate(
            contributor_count=Count(
                f"{PROPOSAL_FUNDRAISE_LOOKUP}__purchases__user",
                distinct=True,
            )
        ).order_by("-contributor_count", "-created_date", "-id")

    def sort_by_amount_raised(self, queryset: QuerySet) -> QuerySet:
        """Sort journal cards by the proposal fundraise amount raised."""
        return queryset.annotate(
            amount_raised=self.build_amount_raised_expression()
        ).order_by("-amount_raised", "-created_date", "-id")

    def build_amount_raised_expression(self, **kwargs: object) -> Coalesce:
        """Build the proposal fundraise amount-raised aggregate expression."""
        return Coalesce(
            Sum(
                F(f"{PROPOSAL_FUNDRAISE_LOOKUP}__escrow__amount_holding")
                + F(f"{PROPOSAL_FUNDRAISE_LOOKUP}__escrow__amount_paid"),
                output_field=DecimalField(max_digits=19, decimal_places=10),
                **kwargs,
            ),
            0,
            output_field=DecimalField(max_digits=19, decimal_places=10),
        )

    def build_open_fundraise_exists(self) -> Exists:
        """Build the open proposal fundraise existence expression."""
        return Exists(
            Fundraise.objects.filter(
                unified_document_id=OuterRef(PROPOSAL_DOCUMENT_ID_OUTER_REF),
                status=Fundraise.OPEN,
            )
        )

    def build_earliest_open_end_date_subquery(self) -> Subquery:
        """Build the earliest open proposal fundraise end-date subquery."""
        earliest_open_end_date = (
            Fundraise.objects.filter(
                unified_document_id=OuterRef(PROPOSAL_DOCUMENT_ID_OUTER_REF),
                status=Fundraise.OPEN,
            )
            .values("end_date")
            .order_by("end_date")[:1]
        )
        return Subquery(earliest_open_end_date, output_field=DateTimeField())
