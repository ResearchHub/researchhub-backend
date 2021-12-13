from django.db.models import Count, Q
import rest_framework.serializers as serializers

from discussion.models import Endorsement, Flag, Vote
from researchhub.serializers import DynamicModelFieldSerializer
from utils.http import get_user_from_request
from utils.sentry import log_error


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


class DynamicVoteSerializer(DynamicModelFieldSerializer):
    class Meta:
        fields = '__all__'
        model = Vote


class GenericReactionSerializerMixin:
    EXPOSABLE_FIELDS = [
      'promoted',
      'score',
      'user_endorsement',
      'user_flag',
      'user_vote',
    ]
    READ_ONLY_FIELDS = [
      'promoted',
      'score',
      'user_endorsement',
      'user_flag',
      'user_vote',
    ]

    def get_document_meta(self, obj):
        paper = obj.paper
        if paper:
            data = {
                'id': paper.id,
                'title': paper.paper_title,
                'slug': paper.slug,
            }
            return data

        post = obj.post
        if post:
            data = {
                'id': post.id,
                'title': post.title,
                'slug': post.slug
            }
            return data

        hypothesis = obj.hypothesis
        if hypothesis:
            data = {
                'id': hypothesis.id,
                'title': hypothesis.title,
                'slug': hypothesis.slug
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

    def get_children_annotated(self, children):
        if self.context.get('needs_score', False):
            upvotes = Count(
                'votes__vote_type',
                filter=Q(votes__vote_type=Vote.UPVOTE)
            )
            downvotes = Count(
                'votes__vote_type',
                filter=Q(votes__vote_type=Vote.DOWNVOTE)
            )
            return children.annotate(
                score=upvotes - downvotes
            )
        else:
            return children

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
        if self.context.get('exclude_promoted_score', False):
            return None
        try:
            return obj.get_promoted_score()
        except Exception as e:
            log_error(e)
            return None
