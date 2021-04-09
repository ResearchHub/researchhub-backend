from django.db.models import Count, Q

import rest_framework.serializers as serializers

from researchhub.settings import PAGINATION_PAGE_SIZE

from .models import (
    Comment,
    Endorsement,
    Flag,
    Thread,
    Reply,
    Vote,
)
from user.serializers import MinimalUserSerializer
from utils.http import get_user_from_request

# TODO: Make is_public editable for creator as a delete mechanism

# TODO: undo


class CensorMixin:

    def get_plain_text(self, obj):
        return self.censor_unless_moderator(obj, obj.plain_text)

    def get_title(self, obj):
        return self.censor_unless_moderator(obj, obj.title)

    def get_text(self, obj):
        return self.censor_unless_moderator(obj, obj.text)

    def censor_unless_moderator(self, obj, value):
        if not obj.is_removed or self.requester_is_moderator():
            return value
        else:
            if type(value) == str:
                return "[{} has been removed]".format(obj._meta.model_name)
            else:
                return None

    def requester_is_moderator(self):
        request = self.context.get('request')
        return (
            request
            and request.user
            and request.user.is_authenticated
            and request.user.moderator
        )


class VoteMixin:

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
            return obj.children.filter(is_removed=False).annotate(score=upvotes - downvotes)
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
                pass
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
        return obj.get_promoted_score()


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


class CommentSerializer(serializers.ModelSerializer, VoteMixin):
    created_by = MinimalUserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    reply_count = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    user_flag = serializers.SerializerMethodField()
    thread_id = serializers.SerializerMethodField()
    paper_id = serializers.SerializerMethodField()
    promoted = serializers.SerializerMethodField()

    class Meta:
        fields = [
            'id',
            'created_by',
            'created_date',
            'created_location',
            'is_public',
            'is_removed',
            'external_metadata',
            'parent',
            'reply_count',
            'replies',
            'score',
            'source',
            'text',
            'updated_date',
            'user_vote',
            'user_flag',
            'was_edited',
            'plain_text',
            'thread_id',
            'paper_id',
            'promoted'
        ]
        read_only_fields = [
            'is_public',
            'is_removed',
            'reply_count',
            'replies',
            'paper_id',
            'score',
            'user_vote',
            'user_flag',
        ]
        model = Comment

    def _replies_query(self, obj):
        return self.get_children_annotated(obj).order_by(
            *self.context.get('ordering', ['-created_date'])
        )

    def get_replies(self, obj):
        if self.context.get('depth', 3) <= 0:
            return []
        reply_queryset = self._replies_query(obj)[:PAGINATION_PAGE_SIZE]

        replies = ReplySerializer(
            reply_queryset,
            many=True,
            context={
                **self.context,
                'depth': self.context.get('depth', 3) - 1,
            },
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
    created_by = MinimalUserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    comment_count = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    user_flag = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()
    paper_slug = serializers.SerializerMethodField()
    promoted = serializers.SerializerMethodField()

    class Meta:
        fields = [
            'block_key',
            'comment_count',
            'comments',
            'context_title',
            'created_by',
            'created_date',
            'created_location',
            'entity_key',
            'external_metadata',
            'id',
            'is_public',
            'is_removed',
            'paper_slug',
            'paper',
            'plain_text',
            'promoted',
            'score',
            'source',
            'text',
            'title',
            'user_flag',
            'user_vote',
            'was_edited',
        ]
        read_only_fields = [
            'is_public',
            'is_removed',
            'score',
            'user_flag',
            'user_vote',
        ]
        model = Thread

    def get_score(self, obj):
        return obj.calculate_score()

    def get_user_vote(self, obj):
        user = get_user_from_request(self.context)
        if user and not user.is_anonymous:
            vote = obj.votes.filter(created_by=user)
            if vote.exists():
                return VoteSerializer(vote.last()).data
            return False
        return False

    def _comments_query(self, obj):
        return self.get_children_annotated(obj).order_by(
            *self.context.get('ordering', ['id'])
        )

    def get_comments(self, obj):
        if self.context.get('depth', 3) <= 0:
            return []
        comments_queryset = self._comments_query(obj)[:PAGINATION_PAGE_SIZE]
        comment_serializer = CommentSerializer(
            comments_queryset,
            many=True,
            context={
                **self.context,
                'depth': self.context.get('depth', 3) - 1,
            },
        )
        return comment_serializer.data

    def get_comment_count(self, obj):
        return self._comments_query(obj).count()

    def get_paper_slug(self, obj):
        if obj.paper:
            return obj.paper.slug


class SimpleThreadSerializer(ThreadSerializer):
    class Meta:
        fields = [
            'id',
        ]
        model = Thread


class ReplySerializer(serializers.ModelSerializer, VoteMixin):
    created_by = MinimalUserSerializer(
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
    user_flag = serializers.SerializerMethodField()
    thread_id = serializers.SerializerMethodField()
    paper_id = serializers.SerializerMethodField()
    reply_count = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()
    promoted = serializers.SerializerMethodField()

    class Meta:
        fields = [
            'id',
            'created_by',
            'created_date',
            'created_location',
            'is_public',
            'is_removed',
            'parent',
            'reply_count',
            'replies',
            'score',
            'text',
            'updated_date',
            'user_vote',
            'user_flag',
            'was_edited',
            'plain_text',
            'thread_id',
            'paper_id',
            'promoted'
        ]
        read_only_fields = [
            'is_public',
            'is_removed',
            'reply_count',
            'replies',
            'score',
            'user_vote',
            'user_flag',
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
        return self.get_children_annotated(obj).order_by(*self.context.get(
            'ordering',
            ['-created_date'])
        )

    def get_replies(self, obj):
        if self.context.get('depth', 3) <= 0:
            return []
        reply_queryset = self._replies_query(obj)[:PAGINATION_PAGE_SIZE]

        replies = ReplySerializer(
            reply_queryset,
            many=True,
            context={
                **self.context,
                'depth': self.context.get('depth', 3) - 1,
            },
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
