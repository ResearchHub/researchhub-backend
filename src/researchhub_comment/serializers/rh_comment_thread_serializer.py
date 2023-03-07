from rest_framework.serializers import ModelSerializer, SerializerMethodField

from discussion.reaction_serializers import GenericReactionSerializerMixin
from researchhub_comment.models import RhCommentThreadModel
from researchhub_comment.serializers.constants.rh_comment_thread_serializer_constants import (
    RH_COMMENT_THREAD_FIELDS,
)
from researchhub_comment.serializers.rh_comment_serializer import RhCommentSerializer


class RhCommentThreadSerializer(ModelSerializer, GenericReactionSerializerMixin):
    class Meta:
        model = RhCommentThreadModel
        fields = [
            *GenericReactionSerializerMixin.EXPOSABLE_FIELDS,
            *RH_COMMENT_THREAD_FIELDS,
        ]

    comments = SerializerMethodField()

    def get_comments(self, thread):
        return RhCommentSerializer(
            thread.rh_comments,
            many=True,
        )
