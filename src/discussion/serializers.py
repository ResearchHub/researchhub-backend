from django.contrib.admin.options import get_content_type_for_model
import rest_framework.serializers as serializers

from .models import Comment, Endorsement, Flag, Thread, Reply, Vote
from user.serializers import UserSerializer
from utils.http import get_user_from_request


# TODO: Make is_public editable for creator as a delete mechanism

class VoteMixin:
    def get_score(self, obj):
        score = self.calculate_score(obj)
        return score

    def calculate_score(self, obj):
        try:
            upvotes = obj.thread_upvotes
        except AttributeError:
            upvotes = obj.votes.filter(vote_type=Vote.UPVOTE)

        try:
            downvotes = obj.thread_upvotes
        except AttributeError:
            downvotes = obj.votes.filter(vote_type=Vote.DOWNVOTE)

        score = len(upvotes) - len(downvotes)
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
            'user_vote',
            'was_edited',
            'plain_text',
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
    score = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    thread = serializers.SerializerMethodField()

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
            'user_vote',
            'was_edited',
            'plain_text',
            'thread',
        ]
        read_only_fields = [
            'is_public',
            'is_removed',
            'score',
            'user_vote'
        ]
        model = Reply

    def get_thread(self, obj):
        current_obj = obj

        while not isinstance(current_obj, Thread) and obj.parent:
            current_obj = current_obj.parent

        if isinstance(current_obj, Thread):
            return ThreadSerializer(current_obj).data
        return None


class CommentSerializer(serializers.ModelSerializer, VoteMixin):
    created_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    reply_count = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    thread = serializers.SerializerMethodField()

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
            'plain_text',
            'thread',
        ]
        read_only_fields = [
            'is_public',
            'is_removed',
            'reply_count',
            'replies',
            'score',
            'user_vote',
        ]
        model = Comment

    def get_replies(self, obj):
        AMOUNT = 20
        request = self.context.get('request')

        reply_queryset = Reply.objects.filter(
            content_type=get_content_type_for_model(obj),
            object_id=obj.id
        ).order_by('-created_date')[:AMOUNT]

        replies = ReplySerializer(
            reply_queryset,
            many=True,
            context={'request': request}
        ).data

        return replies

    def get_reply_count(self, obj):
        replies = self.get_replies(obj)
        count = len(replies)
        return count

    def get_thread(self, obj):
        # TODO: Improve error handling
        try:
            return ThreadSerializer(obj.parent).data
        except Exception:
            return None


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
