from rest_framework.serializers import ModelSerializer, SerializerMethodField

from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_comment.models import RhCommentThreadModel
from researchhub_comment.serializers.constants.rh_comment_thread_serializer_constants import (
    RH_COMMENT_THREAD_FIELDS,
    RH_COMMENT_THREAD_READ_ONLY_FIELDS,
)


class RhCommentThreadSerializer(ModelSerializer):
    comments = SerializerMethodField()

    class Meta:
        model = RhCommentThreadModel
        fields = RH_COMMENT_THREAD_FIELDS
        read_only_fields = RH_COMMENT_THREAD_READ_ONLY_FIELDS

    def get_comments(self, thread):
        from researchhub_comment.serializers import RhCommentSerializer

        return RhCommentSerializer(
            # Only need to fetch top-level comments. Responses are nested comments
            thread.rh_comments.filter(parent__id=None),
            many=True,
        ).data


class DynamicRHThreadSerializer(DynamicModelFieldSerializer):
    comments = SerializerMethodField()

    class Meta:
        fields = "__all__"
        model = RhCommentThreadModel

    def get_comments(self, thread):
        from researchhub_comment.serializers import DynamicRHCommentSerializer

        context = self.context
        _context_fields = context.get("rhc_dts_get_comments", {})
        _filter_fields = _context_fields.get("_filter_fields", {})
        serializer = DynamicRHCommentSerializer(
            thread.rh_comments.filter(**_filter_fields),
            many=True,
            context=context,
            **_context_fields
        )
        return serializer.data
