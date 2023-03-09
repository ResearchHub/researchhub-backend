from django_filters.rest_framework import FilterSet

from researchhub_comment.related_models.rh_comment_thread_model import RhCommentThreadModel

FILTER_FIELDS = [123]
class RhCommentThreadViewFilter(FilterSet):
    class Meta:
        model = RhCommentThreadModel
        fields = FILTER_FIELDS

    # thread_id
