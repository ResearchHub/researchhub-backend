from rest_framework.serializers import ModelSerializer, SerializerMethodField

from hub.serializers import SimpleHubSerializer, DynamicHubSerializer
from paper.serializers import PaperSerializer, DynamicPaperSerializer
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    ELN,
    HYPOTHESIS
)
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.serializers import (
    ResearchhubPostSerializer,
    DynamicPostSerializer
)
from user.serializers import UserSerializer, DynamicUserSerializer


class ResearchhubUnifiedDocumentSerializer(ModelSerializer):
    class Meta(object):
        model = ResearchhubUnifiedDocument
        fields = [
            'access_group',
            'created_by',
            'document_type',
            'documents',
            'hot_score',
            'hubs',
            'is_removed',
            'score',
        ]
        read_only_fields = [
            'access_group',
            'created_by',
            'document_type',
            'documents',
            'hot_score',
            'hubs',
            'hypothesis',
            'id',
            'is_removed',
            'is_public',
            'published_date',
            'paper',
            'posts',
            'score',
        ]

    access_group = SerializerMethodField(method_name='get_access_group')
    created_by = SerializerMethodField(method_name='get_created_by')
    documents = SerializerMethodField(method_name='get_documents')
    hubs = SimpleHubSerializer(
        many=True,
        required=False,
        context={'no_subscriber_info': True}
    ).data

    def get_access_group(self, instance):
        # TODO: calvinhlee - access_group is for ELN. Work on this later
        return None

    def get_created_by(self, instance):
        return UserSerializer(instance.created_by, read_only=True).data

    def get_documents(self, instance):
        context = self.context
        doc_type = instance.document_type
        if (doc_type in [DISCUSSION, ELN]):
            return ResearchhubPostSerializer(
                instance.posts,
                many=True,
                context=context
            ).data
        else:
            return PaperSerializer(instance.paper, context=context).data


class ContributionUnifiedDocumentSerializer(
    ResearchhubUnifiedDocumentSerializer
):
    access_group = None
    hubs = None

    def get_documents(self, instance):
        return None


class DynamicUnifiedDocumentSerializer(DynamicModelFieldSerializer):
    documents = SerializerMethodField()
    created_by = SerializerMethodField()
    access_group = SerializerMethodField()
    hubs = SerializerMethodField()

    class Meta:
        model = ResearchhubUnifiedDocument
        fields = '__all__'

    def get_documents(self, unified_doc):
        context = self.context
        _context_fields = context.get('doc_duds_get_documents', {})
        doc_type = unified_doc.document_type
        if (doc_type in [DISCUSSION, ELN]):
            return DynamicPostSerializer(
                unified_doc.posts,
                many=True,
                context=context,
                **_context_fields
            ).data
        elif doc_type == HYPOTHESIS:
            from hypothesis.serializers import DynamicHypothesisSerializer
            return DynamicHypothesisSerializer(
                unified_doc.hypothesis,
                context=context,
                **_context_fields
            ).data
        else:
            return DynamicPaperSerializer(
                unified_doc.paper,
                context=context,
                **_context_fields
            ).data

    def get_created_by(self, unified_doc):
        context = self.context
        _context_fields = context.get('doc_duds_get_created_by', {})
        serializer = DynamicUserSerializer(
            unified_doc.created_by,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_access_group(self, unified_doc):
        # TODO: calvinhlee - access_group is for ELN. Work on this later
        return

    def get_hubs(self, unified_doc):
        context = self.context
        _context_fields = context.get('doc_duds_get_hubs', {})
        serializer = DynamicHubSerializer(
            unified_doc.hubs,
            many=True,
            context=context,
            **_context_fields
        )
        return serializer.data
