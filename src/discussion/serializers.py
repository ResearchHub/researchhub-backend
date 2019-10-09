import rest_framework.serializers as serializers

from .models import Comment, Thread, Vote
from user.serializers import UserSerializer


# TODO: Add isOwner permission and make is_public editable

class ThreadSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    comment_count = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()

    class Meta:
        fields = [
            'id',
            'title',
            'text',
            'paper',
            'created_by',
            'created_date',
            'is_public',
            'is_removed',
            'comment_count',
            'score',
            'user_vote'
        ]
        read_only_fields = [
            'is_public',
            'is_removed',
            'score',
            'user_vote'
        ]
        model = Thread

    def get_comment_count(self, obj):
        count = len(obj.comments.all())
        return count

    def get_score(self, obj):
        score = calculate_score(obj)
        return score

    def get_user_vote(self, obj):
        vote = None
        user = get_user_from_request(self.context)
        if user:
            try:
                vote = obj.votes.get(created_by=user.id)
                vote = VoteSerializer(vote).data
            except Vote.DoesNotExist:
                pass
        return vote


class CommentSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    score = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()

    class Meta:
        fields = [
            'id',
            'created_by',
            'created_date',
            'updated_date',
            'is_public',
            'is_removed',
            'text',
            'parent',
            'score',
            'user_vote'
        ]
        read_only_fields = [
            'is_public',
            'is_removed',
            'score',
            'user_vote'
        ]
        model = Comment

    def get_score(self, obj):
        score = calculate_score(obj)
        return score

    def get_user_vote(self, obj):
        vote = None
        user = get_user_from_request(self.context)
        if user:
            try:
                vote = obj.votes.get(created_by=user.id)
                vote = VoteSerializer(vote).data
            except Vote.DoesNotExist:
                pass
        return vote


class VoteSerializer(serializers.ModelSerializer):
    item = serializers.PrimaryKeyRelatedField(many=False, read_only=True)

    class Meta:
        fields = [
            'content_type',
            'created_by',
            'created_date',
            'vote_type',
            'item',
        ]
        model = Vote


def calculate_score(obj):
    upvotes = obj.votes.filter(vote_type=Vote.UPVOTE)
    downvotes = obj.votes.filter(vote_type=Vote.DOWNVOTE)
    score = len(upvotes) - len(downvotes)
    return score


def get_user_from_request(ctx):
    request = ctx.get('request')
    if request and hasattr(request, 'user'):
        return request.user
    return None
