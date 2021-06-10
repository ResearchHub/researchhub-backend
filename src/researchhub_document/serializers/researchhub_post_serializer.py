from django.core.files.base import ContentFile
from rest_framework.serializers import ModelSerializer, SerializerMethodField

from hub.models import Hub
from researchhub_document.related_models.constants.document_type \
    import DISCUSSION
from researchhub_document.models import ResearchhubPost
from user.models import User
from user.serializers import UserSerializer


class ResearchhubPostSerializer(ModelSerializer):
    class Meta(object):
        model = ResearchhubPost
        fields = [
            'created_by',
            'document_type',
            'editor_type',
            'is_latest_version',
            'is_root_version',
            'post_src',
            'preview_img',
            'renderable_text',
            'title',
            'unified_document_id',
            'version_number',
        ]
        read_only_fields = [
            'created_by',
            'is_latest_version',
            'is_root_version',
            'post_src',
            'unified_document_id',
            'version_number',
        ]

    created_by = SerializerMethodField(method_name='get_created_by')
    post_src = SerializerMethodField(method_name='get_post_src')
    unified_document_id = SerializerMethodField(
        method_name='get_unified_document_id'
    )

    def create(self, validated_data):
        request_data = self.context.get('request').data
        created_by_user = User.objects.filter(
            id=request_data['created_by_id']
        ).first()
        prev_version = ResearchhubPost.objects.filter(
            id=request_data['prev_version_id']
        ).first()
        hubs = Hub.objects.filter(
          id__in=request_data['hub_ids']
        )
        full_src_file = ContentFile(request_data['full_src'])
        is_discussion = validated_data['document_type'] == DISCUSSION

        return ResearchhubPost.create(
            **validated_data,
            created_by=created_by_user,
            discussion_src=full_src_file if is_discussion else None,
            eln_src=full_src_file if not is_discussion else None,
            hubs=hubs,
            prev_version=prev_version,
        )
  
    def get_post_src(self, instance):
        if (instance.document_type == DISCUSSION):
            return instance.discussion_src
        else:
            return instance.eln_src
  
    def get_created_by(self, instance):
        return UserSerializer(instance.created_by, read_only=True)

    def get_unified_document_id(self, instance):
        unified_document = instance.unified_document
        return instance.unified_document.id \
            if unified_document is not None else None
