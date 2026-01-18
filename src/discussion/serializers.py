import rest_framework.serializers as serializers
from django.db.models import Count, Q
from rest_framework.serializers import (
    ModelSerializer,
    PrimaryKeyRelatedField,
    SerializerMethodField,
)

from discussion.models import Endorsement, Flag, Vote
from hub.serializers import DynamicHubSerializer
from paper.models import Paper
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubPost
from user.models import Author
from user.serializers import DynamicUserSerializer, DynamicVerdictSerializer
from utils.http import get_user_from_request
from utils.sentry import log_error

ORDERING_SCORE_ANNOTATION = Count("id", filter=Q(votes__vote_type=Vote.UPVOTE)) - Count(
    "id", filter=Q(votes__vote_type=Vote.DOWNVOTE)
)


class DynamicFlagSerializer(DynamicModelFieldSerializer):
    item = serializers.SerializerMethodField()
    flagged_by = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()
    hubs = serializers.SerializerMethodField()
    verdict = serializers.SerializerMethodField()

    class Meta:
        model = Flag
        fields = "__all__"

    def get_item(self, flag):
        context = self.context
        item = flag.item

        if isinstance(item, Paper):
            from paper.serializers import DynamicPaperSerializer

            _context_fields = context.get("dis_dfs_get_item", {})
            serializer = DynamicPaperSerializer
        elif isinstance(item, ResearchhubPost):
            from researchhub_document.serializers import DynamicPostSerializer

            _context_fields = context.get("dis_dfs_get_item", {})
            serializer = DynamicPostSerializer
        elif isinstance(item, RhCommentModel):
            from researchhub_comment.serializers import DynamicRhCommentSerializer

            _context_fields = context.get("dis_dfs_get_item", {})
            serializer = DynamicRhCommentSerializer
        elif isinstance(item, Author):
            from user.serializers import DynamicAuthorSerializer

            _context_fields = context.get("dis_dfs_get_author_item", {})
            # Provide default fields for author if not in context
            if not _context_fields:
                _context_fields = {
                    "_include_fields": [
                        "id",
                        "first_name",
                        "last_name",
                        "profile_image",
                    ]
                }
            serializer = DynamicAuthorSerializer
        else:
            return None
        data = serializer(item, context=context, **_context_fields).data

        return data

    def get_flagged_by(self, flag):
        context = self.context
        _context_fields = context.get("dis_dfs_get_created_by", {})
        serializer = DynamicUserSerializer(
            flag.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_content_type(self, flag):
        content_type = flag.content_type
        return {"id": content_type.id, "name": content_type.model}

    def get_hubs(self, flag):
        context = self.context
        _context_fields = context.get("dis_dfs_get_hubs", {})
        serializer = DynamicHubSerializer(
            flag.hubs, many=True, context=context, **_context_fields
        )
        return serializer.data

    def get_verdict(self, flag):
        context = self.context
        verdict = getattr(flag, "verdict", None)

        if not verdict:
            return None

        _context_fields = context.get("dis_dfs_get_verdict", {})
        serializer = DynamicVerdictSerializer(
            verdict, context=context, **_context_fields
        )
        return serializer.data


class EndorsementSerializer(ModelSerializer):
    item = PrimaryKeyRelatedField(many=False, read_only=True)

    class Meta:
        fields = [
            "content_type",
            "created_by",
            "created_date",
            "item",
        ]
        model = Endorsement


class FlagSerializer(ModelSerializer):
    item = PrimaryKeyRelatedField(many=False, read_only=True)
    reason_memo = serializers.CharField(
        max_length=1000, allow_blank=True, allow_null=False, required=False
    )

    class Meta:
        fields = [
            "content_type",
            "created_by",
            "created_date",
            "id",
            "item",
            "reason",
            "reason_choice",
            "reason_memo",
            "object_id",
        ]
        model = Flag


class VoteSerializer(ModelSerializer):
    item = PrimaryKeyRelatedField(many=False, read_only=True)

    class Meta:
        fields = [
            "id",
            "content_type",
            "created_by",
            "created_date",
            "vote_type",
            "item",
        ]
        model = Vote


class DynamicVoteSerializer(DynamicModelFieldSerializer):
    class Meta:
        fields = "__all__"
        model = Vote


class GenericReactionSerializerMixin:
    EXPOSABLE_FIELDS = [
        "promoted",
        "score",
        "user_endorsement",
        "user_flag",
    ]
    READ_ONLY_FIELDS = [
        "promoted",
        "score",
        "user_endorsement",
        "user_flag",
    ]

    def get_document_meta(self, obj):
        paper = obj.paper
        if paper:
            data = {
                "id": paper.id,
                "title": paper.paper_title,
                "slug": paper.slug,
            }
            return data

        post = obj.post
        if post:
            data = {"id": post.id, "title": post.title, "slug": post.slug}
            return data

        return None

    def get_user_endorsement(self, obj):
        user = get_user_from_request(self.context)
        if user:
            try:
                return EndorsementSerializer(
                    obj.endorsements.get(created_by=user.id)
                ).data
            except Endorsement.DoesNotExist:
                return None

    def get_user_flag(self, obj):
        flag = None
        user = get_user_from_request(self.context)
        if user:
            try:
                flag_created_by = obj.flag_created_by
                if len(flag_created_by) == 0:
                    return None
                flag = FlagSerializer(flag_created_by).data
            except AttributeError:
                try:
                    flag = obj.flags.get(created_by=user.id)
                    flag = FlagSerializer(flag).data
                except Flag.DoesNotExist:
                    pass
        return flag

    def get_promoted(self, obj):
        if self.context.get("exclude_promoted_score", False):
            return None
        try:
            return obj.get_promoted_score()
        except Exception as e:
            log_error(e)
            return None


class GenericReactionSerializer(GenericReactionSerializerMixin, ModelSerializer):
    class Meta:
        abstract = True

    promoted = SerializerMethodField()
    user_endorsement = SerializerMethodField()
    user_flag = SerializerMethodField()
    user_vote = SerializerMethodField()
