from rest_framework.serializers import ModelSerializer, SerializerMethodField

from discussion.reaction_models import Vote
from discussion.reaction_serializers import (
    DynamicVoteSerializer,
    GenericReactionSerializerMixin,
)
from hub.serializers import DynamicHubSerializer, SimpleHubSerializer
from hypothesis.models import Hypothesis
from note.serializers import DynamicNoteSerializer, NoteSerializer
from reputation.models import Bounty
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.serializers import DynamicUnifiedDocumentSerializer
from user.serializers import (
    AuthorSerializer,
    DynamicAuthorSerializer,
    DynamicUserSerializer,
    UserSerializer,
)
from utils.http import get_user_from_request


class HypothesisSerializer(ModelSerializer, GenericReactionSerializerMixin):
    class Meta:
        model = Hypothesis
        fields = [
            *GenericReactionSerializerMixin.EXPOSABLE_FIELDS,
            "aggregate_citation_consensus",
            "authors",
            "boost_amount",
            "bounties",
            "created_by",
            "created_date",
            "discussion_count",
            "full_markdown",
            "hubs",
            "id",
            "is_removed",
            "note",
            "renderable_text",
            "slug",
            "src",
            "title",
            "unified_document",
            "vote_meta",
        ]
        read_only_fields = [
            *GenericReactionSerializerMixin.READ_ONLY_FIELDS,
            "aggregate_citation_consensus",
            "authors",
            "boost_amount",
            "bounties",
            "created_by",
            "created_date",
            "discussion_count",
            "id",
            "is_removed",
            "note",
            "renderable_text",
            "slug",
            "src",
            "unified_document",
            "vote_meta",
        ]

    aggregate_citation_consensus = SerializerMethodField()
    authors = AuthorSerializer(many=True)
    boost_amount = SerializerMethodField()
    bounties = SerializerMethodField()
    created_by = UserSerializer()
    discussion_count = SerializerMethodField()
    full_markdown = SerializerMethodField()
    hubs = SerializerMethodField()
    vote_meta = SerializerMethodField()
    note = NoteSerializer()

    # GenericReactionSerializerMixin
    promoted = SerializerMethodField()
    score = SerializerMethodField()
    user_endorsement = SerializerMethodField()
    user_flag = SerializerMethodField()
    user_vote = SerializerMethodField()  # NOTE: calvinhlee - deprecate?

    def get_aggregate_citation_consensus(self, hypothesis):
        return hypothesis.get_aggregate_citation_consensus()

    def get_bounties(self, hypothesis):
        from reputation.serializers import DynamicBountySerializer

        context = {
            "rep_dbs_get_created_by": {"_include_fields": ("author_profile",)},
            "usr_dus_get_author_profile": {
                "_include_fields": (
                    "id",
                    "profile_image",
                    "first_name",
                    "last_name",
                )
            },
        }
        thread_ids = hypothesis.threads.values("id")
        bounties = Bounty.objects.filter(
            item_content_type__model="thread",
            item_object_id__in=thread_ids,
        )
        serializer = DynamicBountySerializer(
            bounties,
            many=True,
            context=context,
            _include_fields=("amount", "created_by", "expiration_date", "status"),
        )
        return serializer.data

    def get_discussion_count(self, hypotheis):
        return hypotheis.get_discussion_count()

    def get_full_markdown(self, hypothesis):
        byte_string = hypothesis.src.read()
        full_markdown = byte_string.decode("utf-8")
        return full_markdown

    def get_hubs(self, hypothesis):
        serializer = SimpleHubSerializer(hypothesis.unified_document.hubs, many=True)
        return serializer.data

    def get_boost_amount(self, hypothesis):
        return hypothesis.get_boost_amount()

    def get_vote_meta(self, hypothesis):
        context = self.context
        _context_fields = context.get("hyp_dcs_get_vote_meta", {})
        votes = hypothesis.votes
        user = get_user_from_request(context)
        user_vote = None

        try:
            if user and not user.is_anonymous:
                user_vote = votes.get(created_by=user)
                serializer = DynamicVoteSerializer(
                    user_vote, context=context, **_context_fields
                )
        except Vote.DoesNotExist:
            pass

        return {
            "down_count": votes.filter(vote_type=Vote.DOWNVOTE).count(),
            "up_count": votes.filter(vote_type=Vote.UPVOTE).count(),
            "user_vote": (serializer.data if user_vote is not None else None),
        }


class DynamicHypothesisSerializer(DynamicModelFieldSerializer):
    aggregate_citation_consensus = SerializerMethodField()
    authors = SerializerMethodField()
    created_by = SerializerMethodField()
    discussion_count = SerializerMethodField()
    hubs = SerializerMethodField()
    note = SerializerMethodField()
    score = SerializerMethodField()
    unified_document = SerializerMethodField()

    class Meta(object):
        model = Hypothesis
        fields = "__all__"

    def get_aggregate_citation_consensus(self, hypothesis):
        return hypothesis.get_aggregate_citation_consensus()

    def get_authors(self, hypothesis):
        context = self.context
        _context_fields = context.get("hyp_dhs_get_authors", {})
        serializer = DynamicAuthorSerializer(
            hypothesis.authors, context=context, many=True, **_context_fields
        )
        return serializer.data

    def get_created_by(self, hypothesis):
        context = self.context
        _context_fields = context.get("hyp_dhs_get_created_by", {})
        serializer = DynamicUserSerializer(
            hypothesis.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_discussion_count(self, hypotheis):
        return hypotheis.get_discussion_count()

    def get_hubs(self, hypothesis):
        context = self.context
        _context_fields = context.get("hyp_dhs_get_hubs", {})
        serializer = DynamicHubSerializer(
            hypothesis.unified_document.hubs,
            many=True,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_note(self, hypothesis):
        context = self.context
        _context_fields = context.get("hyp_dhs_get_note", {})
        serializer = DynamicNoteSerializer(
            hypothesis.note, many=True, context=context, **_context_fields
        )
        return serializer.data

    def get_unified_document(self, hypothesis):
        context = self.context
        _context_fields = context.get("hyp_dhs_get_unified_document", {})
        serializer = DynamicUnifiedDocumentSerializer(
            hypothesis.unified_document, context=context, **_context_fields
        )
        return serializer.data

    def get_score(self, hypothesis):
        return hypothesis.calculate_score()
