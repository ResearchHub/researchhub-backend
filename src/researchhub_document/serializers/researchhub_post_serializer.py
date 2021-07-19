from rest_framework.serializers import ModelSerializer, SerializerMethodField

from discussion.reaction_serializers import GenericReactionSerializerMixin
from hub.serializers import SimpleHubSerializer
from researchhub_document.related_models.constants.document_type \
    import DISCUSSION
from researchhub_document.models import ResearchhubPost
from user.serializers import UserSerializer


class ResearchhubPostSerializer(
    ModelSerializer, GenericReactionSerializerMixin
):
    class Meta(object):
        model = ResearchhubPost
        fields = [
            *GenericReactionSerializerMixin.EXPOSABLE_FIELDS,
            'id',
            'created_by',
            'created_date',
            'discussion_count',
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
            'boost_amount',
            'is_removed'
        ]
        read_only_fields = [
            *GenericReactionSerializerMixin.READ_ONLY_FIELDS,
            'id',
            'created_by',
            'created_date',
            'discussion_count',
            'is_latest_version',
            'is_root_version',
            'post_src',
            'unified_document_id',
            'version_number',
            'boost_amount',
            'is_removed'
        ]

    # GenericReactionSerializerMixin
    promoted = SerializerMethodField()
    boost_amount = SerializerMethodField()
    score = SerializerMethodField()
    user_endorsement = SerializerMethodField()
    user_flag = SerializerMethodField()
    user_vote = SerializerMethodField()

    # local
    created_by = SerializerMethodField(method_name='get_created_by')
    full_markdown = SerializerMethodField(method_name='get_full_markdown')
    hubs = SerializerMethodField(method_name="get_hubs")
    post_src = SerializerMethodField(method_name='get_post_src')
    is_removed = SerializerMethodField()
    unified_document_id = SerializerMethodField(
        method_name='get_unified_document_id'
    )

    def get_post_src(self, instance):
        try:
            if (instance.document_type == DISCUSSION):
                return instance.discussion_src.url
            else:
                return instance.eln_src.url
        except Exception:
            return None

    def get_created_by(self, instance):
        return UserSerializer(instance.created_by, read_only=True).data

    def get_is_removed(self, instance):
        unified_document = instance.unified_document
        return unified_document.is_removed

    def get_unified_document_id(self, instance):
        unified_document = instance.unified_document
        return instance.unified_document.id \
            if unified_document is not None else None

    def get_full_markdown(self, instance):
        try:
            if (instance.document_type == DISCUSSION):
                byte_string = instance.discussion_src.read()
            else:
                byte_string = instance.eln_src.read()
            full_markdown = byte_string.decode('utf-8')
            return full_markdown
        except Exception:
            return None

    def get_hubs(self, instance):
        return SimpleHubSerializer(
            instance.unified_document.hubs, many=True
        ).data

    def get_promoted_score(self, instance):
        return instance.get_promoted_score()

    def get_boost_amount(self, instance):
        return instance.get_boost_amount()
