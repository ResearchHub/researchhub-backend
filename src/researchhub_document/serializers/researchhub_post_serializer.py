from rest_framework.serializers import ModelSerializer, SerializerMethodField

from researchhub_document.models import ResearchhubPost


class ResearchhubPostSerializer(ModelSerializer):
    class Meta(object):
        model = ResearchhubPost
        fields = [
          'document_type',
          'editor_type',
          'is_latest_version',
          'is_root_version',
          'next_version',
          'post_src',
          'prev_version',
          'renderable_text',
          'title',
          'unified_document_id',
          'version_number',
        ]
        read_only_fields = [
          'unified_document_id',
          'is_latest_version',
          ''
        ]