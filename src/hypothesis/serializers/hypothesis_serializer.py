from rest_framework.serializers import ModelSerializer, SerializerMethodField

from discussion.reaction_models import Vote
from hub.serializers import SimpleHubSerializer, DynamicHubSerializer
from hypothesis.models import Hypothesis
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.serializers import (
  DynamicUnifiedDocumentSerializer
)
from discussion.reaction_serializers import (
    DynamicVoteSerializer,
    GenericReactionSerializerMixin
)
from user.serializers import UserSerializer, DynamicUserSerializer
from utils.http import get_user_from_request


class HypothesisSerializer(ModelSerializer, GenericReactionSerializerMixin):
    class Meta:
        model = Hypothesis
        fields = [
            *GenericReactionSerializerMixin.EXPOSABLE_FIELDS,
            'aggregate_citation_consensus',
            'boost_amount',
            'created_by',
            'created_date',
            'full_markdown',
            'hubs',
            'id',
            'renderable_text',
            'result_score',
            'slug',
            'src',
            'title',
            'unified_document',
            'vote_meta',
        ]
        read_only_fields = [
            *GenericReactionSerializerMixin.READ_ONLY_FIELDS,
            'aggregate_citation_consensus',
            'boost_amount',
            'created_by',
            'created_date',
            'id',
            'renderable_text',
            'result_score',
            'slug',
            'src',
            'unified_document',
            'vote_meta',
        ]

    aggregate_citation_consensus = SerializerMethodField()
    boost_amount = SerializerMethodField()
    created_by = UserSerializer()
    full_markdown = SerializerMethodField()
    hubs = SerializerMethodField()
    vote_meta = SerializerMethodField()

    # GenericReactionSerializerMixin
    promoted = SerializerMethodField()
    score = SerializerMethodField()
    user_endorsement = SerializerMethodField()
    user_flag = SerializerMethodField()
    user_vote = SerializerMethodField()  # NOTE: calvinhlee - deprecate?

    def get_aggregate_citation_consensus(self, hypothesis):
        return hypothesis.get_aggregate_citation_consensus()

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

    def get_boost_amount(self, hypothesis):
        return hypothesis.get_boost_amount()

    def get_vote_meta(self, hypothesis):
        context = self.context
        _context_fields = context.get('hyp_dcs_get_vote_meta', {})
        votes = hypothesis.votes
        user = get_user_from_request(context)
        user_vote = None

        try:
            if user and not user.is_anonymous:
                user_vote = votes.get(created_by=user)
                serializer = DynamicVoteSerializer(
                    user_vote,
                    context=context,
                    **_context_fields
                )
        except Vote.DoesNotExist:
            pass

        return (
            {
                'down_count': votes.filter(vote_type=Vote.DOWNVOTE).count(),
                'up_count': votes.filter(vote_type=Vote.UPVOTE).count(),
                'user_vote': (
                    serializer.data
                    if user_vote is not None else None
                )
            }
        )


class DynamicHypothesisSerializer(DynamicModelFieldSerializer):
    aggregate_citation_consensus = SerializerMethodField()
    created_by = SerializerMethodField()
    hubs = SerializerMethodField()
    unified_document = SerializerMethodField()
    score = SerializerMethodField()

    class Meta(object):
        model = Hypothesis
        fields = '__all__'

    def get_aggregate_citation_consensus(self, hypothesis):
        return hypothesis.get_aggregate_citation_consensus()

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

    def get_score(self, hypothesis):
        return hypothesis.calculate_score()
