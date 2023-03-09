from django.contrib.admin.options import get_content_type_for_model
from django_filters import (
    CharFilter,
    ChoiceFilter,
    DateTimeFilter,
    FilterSet,
    NumberFilter,
)

from hypothesis.related_models.citation import Citation
from hypothesis.related_models.hypothesis import Hypothesis
from paper.related_models.paper_model import Paper
from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    RH_COMMENT_THREAD_TYPES,
)
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

FILTER_FIELDS = [
    "created_by",
    "updated_by",
    "thread_type",
    "thread_reference",
]


class RhCommentThreadViewFilter(FilterSet):
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
        label="paper_id",
        method="get_qs_by_paper_id",
    )
    hypothesis_id = NumberFilter(
        field_name="object_id",
        label="paper_id",
        method="get_qs_by_paper_id",
    )
    citation_id = NumberFilter(
        field_name="object_id",
        label="paper_id",
        method="get_qs_by_paper_id",
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

    @property
    def qs(self):
        """
        Intentionally hard limitting queryset to 10.
        At current scale, it's hard to see that we need to fetch more than 10 threads all at once given a query.
        This prevents malicious attempt to overload the server as well.
        """
        return super().qs[:10]
