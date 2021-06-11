from django.db.models import Count, Q
import rest_framework.serializers as serializers

from discussion.models import Endorsement, Flag, Vote
from utils.http import get_user_from_request


class EndorsementSerializer(serializers.ModelSerializer):
    item = serializers.PrimaryKeyRelatedField(many=False, read_only=True)

    class Meta:
        fields = [
            'content_type',
            'created_by',
            'created_date',
            'item',
        ]
        model = Endorsement


class FlagSerializer(serializers.ModelSerializer):
    item = serializers.PrimaryKeyRelatedField(many=False, read_only=True)

    class Meta:
        fields = [
            'content_type',
            'created_by',
            'created_date',
            'item',
            'reason',
        ]
        model = Flag


class VoteSerializer(serializers.ModelSerializer):
    item = serializers.PrimaryKeyRelatedField(many=False, read_only=True)

    class Meta:
        fields = [
            'id',
            'content_type',
            'created_by',
            'created_date',
            'vote_type',
            'item',
        ]
        model = Vote


class GenericReactionSerializerMixin:
    EXPOSABLE_FIELDS = [
      'promoted',
      'score',
      'user_endorsement',
      'user_flag',
      'user_vote'
    ]
    READ_ONLY_FIELDS = [
      'promoted',
      'score',
      'user_endorsement',
      'user_flag',
      'user_vote'
    ]

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
        if self.context.get('needs_score', False):
            return obj.calculate_score()
        else:
            return None

    def get_children_annotated(self, obj):
        if self.context.get('needs_score', False):
            upvotes = Count(
                'votes__vote_type',
                filter=Q(votes__vote_type=Vote.UPVOTE)
            )
            downvotes = Count(
                'votes__vote_type',
                filter=Q(votes__vote_type=Vote.DOWNVOTE)
            )
            return obj.children.filter(is_removed=False).annotate(
              score=upvotes - downvotes
            )
        else:
            return obj.children.filter(is_removed=False)

    def get_user_vote(self, obj):
        vote = None
        user = get_user_from_request(self.context)
        if user:
            try:
                vote = obj.votes.get(created_by=user.id)
                vote = VoteSerializer(vote).data
            except Vote.DoesNotExist:
                return None
        return vote

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
        if self.context.get('exclude_promoted_score', False):
            return None
        try:
            return obj.get_promoted_score()
        except Exception:
            return None
