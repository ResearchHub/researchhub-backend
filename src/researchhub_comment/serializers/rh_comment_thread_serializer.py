from rest_framework.serializers import (
    CharField,
    IntegerField,
    ModelSerializer,
    SerializerMethodField,
)

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
    thread_target_model_name = CharField(source="content_type", read_only=True)
    thread_target_model_instance_id = IntegerField(source="object_id", read_only=True)

    def get_comments(self, thread):
        return RhCommentSerializer(
            # Only need to fetch top-level comments. Responses are nested comments
            thread.rh_comments.filter(parent__id=None),
            many=True,
        ).data
    
