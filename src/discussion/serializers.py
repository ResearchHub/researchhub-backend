from django.contrib.admin.options import get_content_type_for_model
import rest_framework.serializers as serializers

from .models import Comment, Thread, Reply, Vote
from user.serializers import UserSerializer


# TODO: Add isOwner permission and make is_public editable

class VoteMixin:
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


class ReplySerializer(serializers.ModelSerializer, VoteMixin):
    created_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    parent = serializers.PrimaryKeyRelatedField(
        queryset=Comment.objects.all(),
        many=False,
        read_only=False
    )

    class Meta:
        fields = [
            'id',
            'created_by',
            'created_date',
            'is_public',
            'is_removed',
            'parent',
            'score',
            'text',
            'updated_date',
            'user_vote'
            'was_edited',
        ]
        read_only_fields = [
            'is_public',
            'is_removed',
            'score',
            'user_vote'
        ]
        model = Reply


class CommentSerializer(serializers.ModelSerializer, VoteMixin):
    created_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    reply_count = serializers.SerializerMethodField()
    replies = ReplySerializer(read_only=True, many=True)
    score = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()

    class Meta:
        fields = [
            'id',
            'created_by',
            'created_date',
            'is_public',
            'is_removed',
            'parent',
            'reply_count',
            'replies',
            'score',
            'text',
            'updated_date',
            'user_vote',
            'was_edited',
        ]
        read_only_fields = [
            'is_public',
            'is_removed',
            'reply_count',
            'replies',
            'score',
            'user_vote'
        ]
        model = Comment

    def get_replies(self, obj):
        replies = Reply.objects.filter(
            content_type=get_content_type_for_model(obj),
            object_id=obj.id
        )
        return replies

    def get_reply_count(self, obj):
        replies = self.get_replies(obj)
        count = len(replies)
        return count


class ThreadSerializer(serializers.ModelSerializer, VoteMixin):
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
            'comment_count',
            'created_by',
            'created_date',
            'is_public',
            'is_removed',
            'score',
            'user_vote'
            'was_edited',
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
