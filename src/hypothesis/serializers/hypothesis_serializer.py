from rest_framework.serializers import ModelSerializer, SerializerMethodField

from hypothesis.models import Hypothesis
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.serializers import (
  DynamicUnifiedDocumentSerializer
)
from user.serializers import UserSerializer, DynamicUserSerializer


class HypothesisSerializer(ModelSerializer):
    created_by = UserSerializer()

    class Meta:
        model = Hypothesis
        fields = [
            'id',
            'created_by',
            'result_score',
            'slug',
            'unified_document',
            'title'
        ]
        read_only_fields = [
            'id',
            'created_by',
            'result_score',
            'slug',
            'unified_document'
        ]


class DynamicHypothesisSerializer(DynamicModelFieldSerializer):
    created_by = SerializerMethodField()
    unified_document = SerializerMethodField()

    class Meta(object):
        model = Hypothesis
        fields = '__all__'

    def get_created_by(self, hypothesis):
        context = self.context
        _context_fields = context.get('hyp_dhs_get_created_by', {})
        serializer = DynamicUserSerializer(
            hypothesis.created_by,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_unified_document(self, hypothesis):
        context = self.context
        _context_fields = context.get('hyp_dhs_get_unified_document', {})
        serializer = DynamicUnifiedDocumentSerializer(
            hypothesis.unified_document,
            context=context,
            **_context_fields
        )
        return serializer.data
