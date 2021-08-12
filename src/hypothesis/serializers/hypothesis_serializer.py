from rest_framework.serializers import ModelSerializer, SerializerMethodField

from hypothesis.models import Hypothesis
from hub.serializers import SimpleHubSerializer, DynamicHubSerializer
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.serializers import (
  DynamicUnifiedDocumentSerializer
)
from user.serializers import UserSerializer, DynamicUserSerializer
from discussion.reaction_serializers import GenericReactionSerializerMixin


class HypothesisSerializer(ModelSerializer, GenericReactionSerializerMixin):
    created_by = UserSerializer()
    full_markdown = SerializerMethodField()
    hubs = SerializerMethodField()

    class Meta:
        model = Hypothesis
        fields = [
            *GenericReactionSerializerMixin.EXPOSABLE_FIELDS,
            'id',
            'created_by',
            'created_date',
            'full_markdown',
            'hubs',
            'result_score',
            'renderable_text',
            'slug',
            'src',
            'title',
            'unified_document',
            'boost_amount',
        ]
        read_only_fields = [
            *GenericReactionSerializerMixin.READ_ONLY_FIELDS,
            'id',
            'created_by',
            'created_date',
            'result_score',
            'renderable_text',
            'slug',
            'src',
            'unified_document',
            'boost_amount',
        ]

    # GenericReactionSerializerMixin
    promoted = SerializerMethodField()
    boost_amount = SerializerMethodField()
    score = SerializerMethodField()
    user_endorsement = SerializerMethodField()
    user_flag = SerializerMethodField()
    user_vote = SerializerMethodField()

    def get_full_markdown(self, hypothesis):
        byte_string = hypothesis.src.read()
        full_markdown = byte_string.decode('utf-8')
        return full_markdown

    def get_hubs(self, hypothesis):
        serializer = SimpleHubSerializer(
            hypothesis.unified_document.hubs,
            many=True
        )
        return serializer.data

    def get_boost_amount(self, instance):
        return instance.get_boost_amount()


class DynamicHypothesisSerializer(DynamicModelFieldSerializer):
    created_by = SerializerMethodField()
    hubs = SerializerMethodField()
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

    def get_hubs(self, hypothesis):
        context = self.context
        _context_fields = context.get('hyp_dhs_get_hubs', {})
        serializer = DynamicHubSerializer(
            hypothesis.unified_document.hubs,
            many=True,
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
