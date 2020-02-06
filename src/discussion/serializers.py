from django.contrib.admin.options import get_content_type_for_model
from django.db.models import Count, Q

import rest_framework.serializers as serializers

from researchhub.settings import PAGINATION_PAGE_SIZE

from .models import Comment, Endorsement, Flag, Thread, Reply, Vote
from user.serializers import UserSerializer
from utils.http import get_user_from_request

# TODO: Make is_public editable for creator as a delete mechanism

class VoteMixin:

    def get_score(self, obj):
        if self.context.get('needs_score', False):
            return obj.calculate_score()
        else:
            return None

    def get_children_annotated(self, obj):
        if self.context.get('needs_score', False):
            upvotes = Count('votes__vote_type', filter=Q(votes__vote_type=Vote.UPVOTE))
            downvotes = Count('votes__vote_type', filter=Q(votes__vote_type=Vote.DOWNVOTE))
            return obj.children.annotate(score=upvotes - downvotes)
        else:
            return obj.children

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
    paper_id = serializers.SerializerMethodField()

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
            'paper_id',
        ]
        read_only_fields = [
            'is_public',
            'is_removed',
            'reply_count',
            'replies',
            'paper_id',
            'score',
            'user_vote',
        ]
        model = Comment

    def _replies_query(self, obj):
        return self.get_children_annotated(obj).order_by(*self.context.get('ordering', ['-created_date']))

    def get_replies(self, obj):
        reply_queryset = self._replies_query(obj)[:PAGINATION_PAGE_SIZE]

        replies = ReplySerializer(
            reply_queryset,
            many=True,
            context=self.context,
        )

        return replies.data

    def get_reply_count(self, obj):
        replies = self._replies_query(obj)
        return replies.count()

    def get_thread_id(self, obj):
        if isinstance(obj.parent, Thread):
            return obj.parent.id
        return None

    def get_paper_id(self, obj):
        if obj.paper:
            return obj.paper.id
        else:
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
        comments_queryset = self.get_children_annotated(obj).order_by(*self.context.get('ordering', ['-created_date']))[:PAGINATION_PAGE_SIZE]
        comment_serializer = CommentSerializer(
            comments_queryset,
            many=True,
            context=self.context,
        )
        return comment_serializer.data

    def get_comment_count(self, obj):
        return obj.comments.count()

class SimpleThreadSerializer(ThreadSerializer):
    class Meta:
        fields = [
            'id',
        ]
        model = Thread

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
    paper_id = serializers.SerializerMethodField()
    reply_count = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()

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
            'paper_id'
        ]
        read_only_fields = [
            'is_public',
            'is_removed',
            'reply_count',
            'replies',
            'score',
            'user_vote',
            'thread_id',
            'paper_id'
        ]
        model = Reply

    def get_paper_id(self, obj):
        if obj.paper:
            return obj.paper.id
        else:
            return None

    def get_thread_id(self, obj):
        comment = obj.get_comment_of_reply()
        if comment and isinstance(comment.parent, Thread):
            return comment.parent.id
        return None

    def _replies_query(self, obj):
        return self.get_children_annotated(obj).order_by(*self.context.get('ordering', ['-created_date']))

    def get_replies(self, obj):
        reply_queryset = self._replies_query(obj)[:PAGINATION_PAGE_SIZE]

        replies = ReplySerializer(
            reply_queryset,
            many=True,
            context=self.context,
        )

        return replies.data

    def get_reply_count(self, obj):
        replies = self._replies_query(obj)
        return replies.count()

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
