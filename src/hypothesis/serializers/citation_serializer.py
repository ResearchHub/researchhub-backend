from rest_framework.serializers import ModelSerializer, SerializerMethodField

from hypothesis.models import Citation
from hypothesis.serializers import (
    HypothesisSerializer,
    DynamicHypothesisSerializer
)
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.serializers import (
    ResearchhubUnifiedDocumentSerializer,
    DynamicUnifiedDocumentSerializer
)
from user.serializers import UserSerializer, DynamicUserSerializer


class CitationSerializer(ModelSerializer):
    created_by = UserSerializer()
    source = ResearchhubUnifiedDocumentSerializer()
    hypothesis = HypothesisSerializer()

    class Meta:
        model = Citation
        fields = [
            'id',
            'created_by',
            'hypothesis',
            'source',
        ]
        read_only_fields = [
            'id',
        ]


class DynamicCitationSerializer(DynamicModelFieldSerializer):
    created_by = SerializerMethodField()
    hypothesis = SerializerMethodField()
    source = SerializerMethodField()

    class Meta(object):
        model = Citation
        fields = '__all__'

    def get_created_by(self, citation):
        context = self.context
        _context_fields = context.get('hyp_dcs_get_created_by', {})
        serializer = DynamicUserSerializer(
            citation.created_by,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_hypothesis(self, citation):
        context = self.context
        _context_fields = context.get('hyp_dcs_get_hypothesis', {})
        serializer = DynamicHypothesisSerializer(
            citation.hypothesis,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_source(self, citation):
        context = self.context
        _context_fields = context.get('hyp_dcs_get_source', {})
        serializer = DynamicUnifiedDocumentSerializer(
            citation.source,
            context=context,
            **_context_fields
        )
        return serializer.data
