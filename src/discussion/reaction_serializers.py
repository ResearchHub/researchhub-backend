from rest_framework.serializers import (
    ModelSerializer,
    PrimaryKeyRelatedField,
    SerializerMethodField,
)

from discussion.reaction_models import Endorsement, Flag, Vote
from researchhub.serializers import DynamicModelFieldSerializer
from utils.http import get_user_from_request
from utils.sentry import log_error


def raise_implement(class_name, method_name):
    raise NotImplementedError(f"{class_name}: must implement {method_name}")


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

    class Meta:
        fields = [
            "content_type",
            "created_by",
            "created_date",
            "id",
            "item",
            "reason",
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
        "user_vote",
    ]
    READ_ONLY_FIELDS = [
        "promoted",
        "score",
        "user_endorsement",
        "user_flag",
        "user_vote",
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

        hypothesis = obj.hypothesis
        if hypothesis:
            data = {
                "id": hypothesis.id,
                "title": hypothesis.title,
                "slug": hypothesis.slug,
            }
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

    def get_score(self, obj):
        try:
            return obj.calculate_score()
        except Exception as e:
            log_error(e)
            return None

    def get_user_vote(self, obj):
        vote = None
        user = get_user_from_request(self.context)
        try:
            if user and not user.is_anonymous:
                vote = obj.votes.get(created_by=user)
                vote = VoteSerializer(vote).data
            return vote
        except Vote.DoesNotExist:
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
        # NOTE: fields = [raise_implement("GenericReactionSerializer", "fields")]
        # NOTE: read_only_fields = [raise_implement("GenericReactionSerializer", "read_only_fields")]

    promoted = SerializerMethodField()
    score = SerializerMethodField()
    user_endorsement = SerializerMethodField()
    user_flag = SerializerMethodField()
    user_vote = SerializerMethodField()
