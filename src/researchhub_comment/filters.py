from django.db.models import Count, Q
from django_filters import (
    CharFilter,
    ChoiceFilter,
    DateTimeFilter,
    FilterSet,
    NumberFilter,
)
from django_filters import rest_framework as filters

from discussion.reaction_models import Vote
from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    RH_COMMENT_THREAD_TYPES,
)
from researchhub_comment.models import RhCommentModel

BEST = "BEST"
TOP = "TOP"
CREATED_DATE = "CREATED_DATE"
ASCENDING_TRUE = "TRUE"
ASCENDING_FALSE = "FALSE"

ORDER_CHOICES = ((BEST, "Best"), (TOP, "Top"), (CREATED_DATE, "Created Date"))
ASCENDING_CHOICES = ((ASCENDING_TRUE, "Ascending"), (ASCENDING_FALSE, "Descending"))


class RHCommentFilter(filters.FilterSet):
    created_date__gte = DateTimeFilter(
        field_name="created_date",
        lookup_expr="gte",
    )
    created_date__lt = DateTimeFilter(
        field_name="created_date",
        lookup_expr="lt",
    )
    updated_date__gte = DateTimeFilter(
        field_name="updated_date",
        lookup_expr="gte",
    )
    updated_date__lt = DateTimeFilter(
        field_name="updated_date",
        lookup_expr="lt",
    )
    ordering = filters.ChoiceFilter(
        method="ordering_filter",
        choices=ORDER_CHOICES,
        null_value=BEST,
        label="Ordering",
    )
    ascending = filters.ChoiceFilter(
        method="ascending_or_descending",
        choices=ASCENDING_CHOICES,
        null_value=ASCENDING_FALSE,
        label="Ascending",
    )

    class Meta:
        model = RhCommentModel
        fields = ("ordering",)

    def ascending_or_descending(self, qs, name, value):
        if value == ASCENDING_FALSE:
            return qs.reverse()
        return qs

    def ordering_filter(self, qs, name, value):
        if value == BEST:
            # TODO: Implement when bounty is merged in
            pass
        elif value == TOP:
            qs = qs.annotate(
                aggregate_score=(
                    Count("votes__id", filter=Q(votes__vote_type=Vote.UPVOTE))
                    - Count("votes__id", filter=Q(votes__vote_type=Vote.DOWNVOTE))
                )
            ).order_by("aggregate_score")
        elif value == CREATED_DATE:
            qs = qs.order_by("created_date")
        return qs
