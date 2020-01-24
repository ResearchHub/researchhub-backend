from django.contrib.admin.options import get_content_type_for_model
import rest_framework.serializers as serializers

from researchhub.settings import PAGINATION_PAGE_SIZE

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

class CommentSerializer(serializers.ModelSerializer, VoteMixin):
    created_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    reply_count = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    thread_id = serializers.SerializerMethodField()

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
            'thread_id',
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

    def _replies_query(self, obj):
        return Reply.objects.filter(
            content_type=get_content_type_for_model(obj),
            object_id=obj.id
        ).order_by('-created_date')

    def get_replies(self, obj):
        reply_queryset = self._replies_query(obj)[:PAGINATION_PAGE_SIZE]

        replies = ReplySerializer(
            reply_queryset,
            many=True,
        )

        return replies.data

    def get_reply_count(self, obj):
        replies = self._replies_query(obj)
        return replies.count()

    def get_thread_id(self, obj):
        if isinstance(obj.parent, Thread):
            return obj.parent.id
        return None

class ThreadSerializer(serializers.ModelSerializer, VoteMixin):
    created_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    comment_count = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()

    class Meta:
        fields = [
            'id',
            'title',
            'text',
            'paper',
            'comment_count',
            'comments',
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

    def get_comments(self, obj):
        comments_queryset = obj.comments.all().order_by('-created_date')[:PAGINATION_PAGE_SIZE]
        comment_serializer = CommentSerializer(
            comments_queryset,
            many=True,
        )
        return comment_serializer.data

    def get_comment_count(self, obj):
        return obj.comments.count()

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
    thread_id = serializers.SerializerMethodField()

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
            'thread_id',
        ]
        read_only_fields = [
            'is_public',
            'is_removed',
            'score',
            'user_vote'
        ]
        model = Reply

    def get_thread_id(self, obj):
        current_obj = obj

        while not isinstance(current_obj, Thread) and obj.parent:
            current_obj = current_obj.parent

        if isinstance(current_obj, Thread):
            return current_obj.id
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
