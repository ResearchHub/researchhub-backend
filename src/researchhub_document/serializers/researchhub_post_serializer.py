from rest_framework.serializers import ModelSerializer, SerializerMethodField

from discussion.reaction_serializers import VoteSerializerMixin
from hub.serializers import SimpleHubSerializer
from researchhub_document.related_models.constants.document_type \
    import DISCUSSION
from researchhub_document.models import ResearchhubPost
from user.serializers import UserSerializer
from utils.http import get_user_from_request


class ResearchhubPostSerializer(ModelSerializer, VoteSerializerMixin):
    class Meta(object):
        model = ResearchhubPost
        fields = [
            'created_by',
            'document_type',
            'editor_type',
            'full_markdown',
            'hubs',
            'is_latest_version',
            'is_root_version',
            'post_src',
            'preview_img',
            'renderable_text',
            'title',
            'unified_document_id',
            'version_number',
            'user_vote',  # VoteSerializerMixin
        ]
        read_only_fields = [
            'created_by',
            'is_latest_version',
            'is_root_version',
            'post_src',
            'unified_document_id',
            'version_number',
            'user_vote',  # VoteSerializerMixin
        ]

    created_by = SerializerMethodField(method_name='get_created_by')
    post_src = SerializerMethodField(method_name='get_post_src')
    unified_document_id = SerializerMethodField(
        method_name='get_unified_document_id'
    )
    full_markdown = SerializerMethodField(method_name='get_full_markdown')
    hubs = SerializerMethodField(method_name="get_hubs")

    def get_post_src(self, instance):
        if (instance.document_type == DISCUSSION):
            return instance.discussion_src.url
        else:
            return instance.eln_src.url

    def get_created_by(self, instance):
        return UserSerializer(instance.created_by, read_only=True).data

    def get_unified_document_id(self, instance):
        unified_document = instance.unified_document
        return instance.unified_document.id \
            if unified_document is not None else None

    def get_full_markdown(self, instance):
        if (instance.document_type == DISCUSSION):
            byte_string = instance.discussion_src.read()
        else:
            byte_string = instance.eln_src.read()
        full_markdown = byte_string.decode('utf-8')
        return full_markdown

    def get_hubs(self, instance):
        return SimpleHubSerializer(
            instance.unified_document.hubs, many=True
        ).data
