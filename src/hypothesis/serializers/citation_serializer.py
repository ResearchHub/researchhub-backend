from discussion.models import Thread
from rest_framework.serializers import ModelSerializer, SerializerMethodField
from discussion.reaction_models import Vote
from discussion.reaction_serializers import (
    GenericReactionSerializerMixin,
    DynamicVoteSerializer
)

from hypothesis.models import Citation
from hypothesis.serializers import (
    DynamicHypothesisSerializer
)
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.serializers import (
    ResearchhubUnifiedDocumentSerializer,
    DynamicUnifiedDocumentSerializer
)
from user.serializers import UserSerializer, DynamicUserSerializer
from utils.http import get_user_from_request


class CitationSerializer(ModelSerializer, GenericReactionSerializerMixin):
    created_by = UserSerializer()
    source = ResearchhubUnifiedDocumentSerializer()

    class Meta:
        model = Citation
        fields = [
            *GenericReactionSerializerMixin.EXPOSABLE_FIELDS,
            'boost_amount',
            'citation_type',
            'created_by',
            'id',
            'source',
        ]
        read_only_fields = [
            *GenericReactionSerializerMixin.READ_ONLY_FIELDS,
            'id',
        ]

    boost_amount = SerializerMethodField()

    # GenericReactionSerializerMixin
    promoted = SerializerMethodField()
    score = SerializerMethodField()
    user_endorsement = SerializerMethodField()
    user_flag = SerializerMethodField()
    user_vote = SerializerMethodField()

    def get_boost_amount(self, citation):
        # TODO: leo | thomasvu - add logic / instance method
        return 0


class DynamicCitationSerializer(DynamicModelFieldSerializer):
    consensus_meta = SerializerMethodField()
    created_by = SerializerMethodField()
    hypothesis = SerializerMethodField()
    inline_comment_count = SerializerMethodField()
    publish_date = SerializerMethodField()
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
    
    def get_publish_date(self, citation):
        return citation.source.paper.paper_publish_date

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
        context = self.context
        _context_fields = context.get('hyp_dcs_get_consensus_meta', {})

        votes = citation.votes
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
                'neutral_count': votes.filter(vote_type=Vote.NEUTRAL).count(),
                'total_count': votes.count(),
                'up_count': votes.filter(vote_type=Vote.UPVOTE).count(),
                'user_vote': (
                    serializer.data
                    if user_vote is not None else None
                )
            }
        )

    def get_inline_comment_count(self, citation):
        return Thread.objects.filter(citation__id=citation.id).count() or 0
