from rest_framework.serializers import SerializerMethodField, IntegerField
from discussion.reaction_serializers import (
    GenericReactionSerializer,
    GenericReactionSerializerMixin,
)
from researchhub_comment.models import RhCommentModel
from researchhub_comment.serializers.constants.rh_comment_serializer_contants import (
    RH_COMMENT_FIELDS,
    RH_COMMENT_READ_ONLY_FIELDS,
)

from utils.sentry import log_error


class RhCommentSerializer(GenericReactionSerializer):
    class Meta:
        model = RhCommentModel
        fields = [
            *GenericReactionSerializerMixin.EXPOSABLE_FIELDS,
            *RH_COMMENT_FIELDS,
        ]
        read_only_fields = [
            *GenericReactionSerializerMixin.READ_ONLY_FIELDS,
            *RH_COMMENT_READ_ONLY_FIELDS,
        ]

    parent_id = IntegerField(source="parent.id", default=None)
    children = SerializerMethodField()
    thread_id = IntegerField(source="thread.id", default=None)

    def get_children(self, rh_comment):
        return RhCommentSerializer(
            instance=rh_comment.children,
            many=True,
        ).data
