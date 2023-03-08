from rest_framework.serializers import ModelSerializer, SerializerMethodField

from discussion.reaction_serializers import GenericReactionSerializerMixin
from researchhub_comment.models import RhCommentThreadModel
from researchhub_comment.serializers.constants.rh_comment_thread_serializer_constants import (
    RH_COMMENT_THREAD_FIELDS,
    RH_COMMENT_THREAD_READ_ONLY_FIELDS,
)
from researchhub_comment.serializers.rh_comment_serializer import RhCommentSerializer


class RhCommentThreadSerializer(ModelSerializer):
    class Meta:
        model = RhCommentThreadModel
        fields = RH_COMMENT_THREAD_FIELDS
        read_only_fields = RH_COMMENT_THREAD_READ_ONLY_FIELDS

    comments = SerializerMethodField()

    def get_comments(self, thread):
        return RhCommentSerializer(
            thread.rh_comments,
            many=True,
        ).data
