from functools import reduce

from django.db.models import DecimalField, IntegerField, Q, Sum
from django.db.models.functions import Cast, Coalesce
from django_filters import DateTimeFilter
from django_filters import rest_framework as filters

from reputation.models import Bounty
from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    INNER_CONTENT_COMMENT,
    RH_COMMENT_THREAD_TYPES,
    SUMMARY,
)
from researchhub_comment.models import RhCommentModel

BEST = "BEST"
TOP = "TOP"
BOUNTY = "BOUNTY"
REVIEW = "REVIEW"
DISCUSSION = "DISCUSSION"
CREATED_DATE = "CREATED_DATE"
ASCENDING_TRUE = "TRUE"
ASCENDING_FALSE = "FALSE"

ORDER_CHOICES = (
    (BEST, "Best"),
    (TOP, "Top"),
    (CREATED_DATE, "Created Date"),
)

FILTER_CHOICES = (
    (BOUNTY, "Has Bounty"),
    (REVIEW, REVIEW),
    (DISCUSSION, DISCUSSION),
    (INNER_CONTENT_COMMENT, INNER_CONTENT_COMMENT),
)


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
    filtering = filters.ChoiceFilter(
        method="filtering_filter",
        choices=FILTER_CHOICES,
        label="Filter by",
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
        if not self._is_ascending():
            return [f"-{key}" for key in keys]
        return keys

    def _annotate_bounty_sum(self, qs, annotation_filters=None):
        annotation_filters = [] if annotation_filters is None else annotation_filters
        annotation_filters_query = reduce(
            lambda q, value: q | Q(**value), annotation_filters, Q()
        )
        queryset = qs.annotate(
            bounty_sum=Coalesce(
                Sum("bounties__amount", filter=annotation_filters_query),
                0,
                output_field=DecimalField(),
            )
        )
        return queryset

    def _is_on_child_queryset(self):
        # This checks whether we are filtering on the comment's children
        # because we don't want the related filters to be called
        # on the base comments, only children
        instance_class_name = self.queryset.__class__.__name__
        if instance_class_name == "RelatedManager":
            return True

    def ordering_filter(self, qs, name, value):
        if value == BEST:
            qs = self._annotate_bounty_sum(
                qs, annotation_filters=[{"bounties__status": Bounty.OPEN}]
            )
            qs = qs.annotate(
                accepted_answer=Cast("is_accepted_answer", output_field=IntegerField())
            )
            keys = self._get_ordering_keys(
                [
                    "bounty_sum",
                    "accepted_answer",
                    "score",
                    "created_date",
                ]
            )
            qs = qs.order_by(*keys)
        elif value == TOP:
            keys = self._get_ordering_keys(["score"])
            qs = qs.order_by(*keys)
        elif value == BOUNTY:
            qs = self._annotate_bounty_sum(qs).filter(bounty_sum__gt=0)
            keys = self._get_ordering_keys(
                [
                    "bounty_sum",
                    "score",
                    "created_date",
                ]
            )
        elif value == CREATED_DATE:
            keys = self._get_ordering_keys(["created_date"])
            qs = qs.order_by(*keys)
        return qs

    def filtering_filter(self, qs, name, value):
        if self._is_on_child_queryset():
            return qs

        if value == BOUNTY:
            qs = qs.filter(bounties__isnull=False)
            qs = self._annotate_bounty_sum(
                qs, annotation_filters=[{"bounties__status": Bounty.OPEN}]
            )
        elif value == REVIEW:
            qs = qs.filter(thread__thread_type=REVIEW)
        elif value == INNER_CONTENT_COMMENT:
            qs = qs.filter(thread__thread_type=INNER_CONTENT_COMMENT)
        elif value == DISCUSSION:
            qs = qs.filter(
                (Q(thread__thread_type=GENERIC_COMMENT) & Q(bounties__isnull=True))
                | Q(thread__thread_type=SUMMARY)
            )

        return qs

    def filter_child_count(self, qs, name, value):
        if not self._is_on_child_queryset():
            return qs
        offset = int(self.data.get("child_offset", 0))
        count = offset + value

        # Returning the slice qs[offset:count] will cause an error
        # if the queryset has additional filtering
        sliced_children_ids = qs[offset:count].values_list("id")
        return qs.filter(id__in=sliced_children_ids)
