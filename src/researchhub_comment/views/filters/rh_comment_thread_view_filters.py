from django_filters import (
    ChoiceFilter,
    FilterSet,
    NumberFilter,
    DateTimeFilter,
    CharFilter,
)
from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    RH_COMMENT_THREAD_TYPES,
)

from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from user.related_models.user_model import User

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

    thread_id = NumberFilter(field_name="id", label="thread_id")
    created_date__gte = DateTimeFilter(
        field_name="created_date",
        lookup_expr="gte",
    )
    created_date__lt = DateTimeFilter(
        field_name="created_date",
        lookup_expr="lt",
    )
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

    @property
    def qs(self):
        """
        Intentionally hard limitting queryset to 10.
        At current scale, it's hard to see that we need to fetch more than 10 threads all at once given a query.
        This prevents malicious attempt to overload the server as well.
        """
        return super().qs[:10]
