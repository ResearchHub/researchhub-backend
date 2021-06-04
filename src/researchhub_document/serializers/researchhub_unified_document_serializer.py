from rest_framework.serializers import ModelSerializer, SerializerMethodField

from hub.serializers import SimpleHubSerializer
from paper.serializers import PaperSerializer
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION, ELN
)
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.serializers import ResearchhubPostSerializer
from user.serializers import UserSerializer


class ResearchhubUnifiedDocumentSerializer(ModelSerializer):
    class Meta(object):
        model = ResearchhubUnifiedDocument
        fields = [
          'access_group',
          'created_by',
          'document_type',
          'hot_score',
          'hubs',
          'documents',
        ]
        read_only_fields = [
          'access_group',
          'created_by',
          'document_type',
          'hot_score',
          'hubs',
          'documents',
        ]

    access_group = SerializerMethodField(method_name="get_access_group")
    created_by = SerializerMethodField(method_name="get_created_by")
    documents = SerializerMethodField(method_name="get_documents")
    hubs = SimpleHubSerializer(
        many=True,
        required=False,
        context={'no_subscriber_info': True}
    )

    def get_access_group(self, instance):
        # TODO: calvinhlee - access_group is for ELN. Work on this later
        return []

    def get_created_by(self, instance):
        return UserSerializer(instance.created_by, read_only=True)

    def get_documents(self, instance):
        doc_type = instance.document_type
        if (doc_type in [DISCUSSION, ELN]):
            return ResearchhubPostSerializer(instance.posts, many=True)
        else:
            return PaperSerializer(instance.paper)

