from rest_framework.serializers import ModelSerializer, SerializerMethodField
from discussion.reaction_models import Vote
from discussion.reaction_serializers import (
    GenericReactionSerializerMixin,
    VoteSerializer
)

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
from utils.http import get_user_from_request


class CitationSerializer(ModelSerializer):
    created_by = UserSerializer()
    source = ResearchhubUnifiedDocumentSerializer()
    hypothesis = HypothesisSerializer()

    class Meta:
        model = Citation
        fields = [
            *GenericReactionSerializerMixin.EXPOSABLE_FIELDS,
            'id',
            'created_by',
            'hypothesis',
            'source',
        ]
        read_only_fields = [
            *GenericReactionSerializerMixin.READ_ONLY_FIELDS,
            'id',
        ]

    # GenericReactionSerializerMixin
    promoted = SerializerMethodField()
    boost_amount = SerializerMethodField()
    score = SerializerMethodField()
    user_endorsement = SerializerMethodField()
    user_flag = SerializerMethodField()
    user_vote = SerializerMethodField()


class DynamicCitationSerializer(DynamicModelFieldSerializer):
    consensus_meta = SerializerMethodField()
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

    def get_consensus_meta(self, citation):
        votes = citation.votes
        user = get_user_from_request(self.context)
        user_vote = None
        try:
            if user and not user.is_anonymous:
                user_vote = citation.votes.get(created_by=user)
        except Vote.DoesNotExist:
            pass

        return (
            {
                'down_count': votes.filter(vote_type=Vote.DOWNVOTE).count(),
                'up_count': votes.filter(vote_type=Vote.UPVOTE).count(),
                'user_vote': (
                    VoteSerializer(user_vote).data
                    if user_vote is not None else None
                )
            }
        )
