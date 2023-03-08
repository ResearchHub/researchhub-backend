from rest_framework.serializers import ModelSerializer, SerializerMethodField
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

    comment_content_markdown = SerializerMethodField()

    def get_comment_content_markdown(self, rh_comment):
        try:
            return rh_comment.comment_content_src.read().decode("utf-8")
        except Exception as e:
            log_error(f"get_comment_content_markdown: {e}")
