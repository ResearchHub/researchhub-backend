from django.contrib.admin.options import get_content_type_for_model
from django_filters import (
    CharFilter,
    ChoiceFilter,
    DateTimeFilter,
    FilterSet,
    NumberFilter,
)
from django_filters import rest_framework as filters

from hypothesis.related_models.citation import Citation
from hypothesis.related_models.hypothesis import Hypothesis
from paper.related_models.paper_model import Paper
from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    RH_COMMENT_THREAD_TYPES,
)
from researchhub_comment.models import RhCommentThreadModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

BEST = "BEST"
TOP = "TOP"
CREATED_DATE = "CREATED_DATE"

ORDER_CHOICES = ((BEST, "Best"), (TOP, "Top"), (CREATED_DATE, "Created Date"))


class RHCommentFilter(filters.FilterSet):
    ordering = filters.ChoiceFilter(
        method="ordering_filter",
        choices=ORDER_CHOICES,
        null_value=BEST,
    )

    class Meta:
        model = RhCommentThreadModel
        fields = ("ordering",)

    def ordering_filter(self, qs, name, value):
        print(name, value)
        pass
        return qs


FILTER_FIELDS = [
    "created_by",
    "updated_by",
    "thread_type",
    "thread_reference",
]


class RhCommentThreadFilter(FilterSet):
    class Meta:
        model = RhCommentThreadModel
        fields = FILTER_FIELDS

    created_date__gte = DateTimeFilter(
        field_name="created_date",
        lookup_expr="gte",
    )
    created_date__lt = DateTimeFilter(
        field_name="created_date",
        lookup_expr="lt",
    )
    thread_id = NumberFilter(field_name="id", label="thread_id")
    thread_reference = CharFilter(lookup_expr="iexact")
    thread_type = ChoiceFilter(
        field_name="thread_type",
        choices=RH_COMMENT_THREAD_TYPES,
        null_value=GENERIC_COMMENT,
    )
    updated_date__gte = DateTimeFilter(
        field_name="updated_date",
        lookup_expr="gte",
    )
    updated_date__lt = DateTimeFilter(
        field_name="updated_date",
        lookup_expr="lt",
    )

    """ ---- Generic Reaction Filters ---"""
    paper_id = NumberFilter(
        field_name="object_id",
        label="paper_id",
        method="get_qs_by_paper_id",
    )
    researchhub_post_id = NumberFilter(
        field_name="object_id",
        label="researchhub_post_id",
        method="get_qs_by_researchhub_post_id",
    )
    hypothesis_id = NumberFilter(
        field_name="object_id",
        label="hypothesis_id",
        method="get_qs_by_hypothesis_id",
    )
    citation_id = NumberFilter(
        field_name="object_id",
        label="citation_id",
        method="get_qs_by_citation_id",
    )

    def get_qs_by_paper_id(self, qs, name, value):
        return qs.filter(
            content_type=get_content_type_for_model(Paper), object_id=int(value)
        )

    def get_qs_by_researchhub_post_id(self, qs, name, value):
        return qs.filter(
            content_type=get_content_type_for_model(ResearchhubPost),
            object_id=int(value),
        )

    def get_qs_by_hypothesis_id(self, qs, name, value):
        return qs.filter(
            content_type=get_content_type_for_model(Hypothesis), object_id=int(value)
        )

    def get_qs_by_citation_id(self, qs, name, value):
        return qs.filter(
            content_type=get_content_type_for_model(Citation), object_id=int(value)
        )
