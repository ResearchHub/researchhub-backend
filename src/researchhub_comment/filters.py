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
        required=True,
    )
    child_count = filters.NumberFilter(
        method="filter_child_count",
        label="Child Comment Count",
        required=True,
    )
    thread_type = filters.ChoiceFilter(
        choices=RH_COMMENT_THREAD_TYPES,
        field_name="thread__thread_type",
        label="Thread Type",
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

    def _is_on_child_queryset(self):
        # This checks whether we are filtering on the comment's children
        # because we don't want the related filters to be called
        # on the base comments, only children
        instance_class_name = self.queryset.__class__.__name__
        if instance_class_name == "RelatedManager":
            return True

    def ascending_or_descending(self, qs, name, value):
        if value == ASCENDING_FALSE:
            return qs.reverse()
        return qs

    def ordering_filter(self, qs, name, value):
        if value == BEST:
            # TODO: Implement when bounty is merged in
            qs = qs.order_by("score", "created_date")
        elif value == TOP:
            qs = qs.order_by("score")
        elif value == CREATED_DATE:
            qs = qs.order_by("created_date")
        return qs

    def filter_child_count(self, qs, name, value):
        if not self._is_on_child_queryset():
            return qs
        offset = int(self.data.get("child_offset", 0))
        count = offset + value
        return qs[offset:count]
