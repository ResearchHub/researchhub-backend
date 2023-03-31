from django_filters import DateTimeFilter
from django_filters import rest_framework as filters

from researchhub_comment.constants.rh_comment_thread_types import (
    RH_COMMENT_THREAD_TYPES,
)
from researchhub_comment.models import RhCommentModel

BEST = "BEST"
TOP = "TOP"
CREATED_DATE = "CREATED_DATE"
ASCENDING_TRUE = "TRUE"
ASCENDING_FALSE = "FALSE"

ORDER_CHOICES = ((BEST, "Best"), (TOP, "Top"), (CREATED_DATE, "Created Date"))


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
    child_count = filters.NumberFilter(
        method="filter_child_count",
        label="Child Comment Count",
    )
    thread_type = filters.ChoiceFilter(
        choices=RH_COMMENT_THREAD_TYPES,
        field_name="thread__thread_type",
        label="Thread Type",
    )

    class Meta:
        model = RhCommentModel
        fields = ("ordering",)

    def _is_ascending(self):
        return self.data.get("ascending", ASCENDING_FALSE) == ASCENDING_TRUE

    def _get_ordering_keys(self, keys):
        if self._is_ascending():
            return [f"-{key}" for key in keys]
        return keys

    def _is_on_child_queryset(self):
        # This checks whether we are filtering on the comment's children
        # because we don't want the related filters to be called
        # on the base comments, only children
        instance_class_name = self.queryset.__class__.__name__
        if instance_class_name == "RelatedManager":
            return True

    def ordering_filter(self, qs, name, value):
        if value == BEST:
            # TODO: Implement when bounty is merged in
            keys = self._get_ordering_keys(["score", "created_date"])
            qs = qs.order_by(*keys)
        elif value == TOP:
            keys = self._get_ordering_keys(["score"])
            qs = qs.order_by(*keys)
        elif value == CREATED_DATE:
            keys = self._get_ordering_keys(["created_date"])
            qs = qs.order_by(*keys)
        return qs

    def filter_child_count(self, qs, name, value):
        if not self._is_on_child_queryset():
            return qs
        offset = int(self.data.get("child_offset", 0))
        count = offset + value
        return qs[offset:count]
