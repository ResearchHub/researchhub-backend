import rest_framework.serializers as serializers

from discussion.models import Comment, Thread, Reply
from discussion.reaction_serializers import (
    VoteSerializer,
    GenericReactionSerializerMixin,
    DynamicVoteSerializer  # Import is needed for discussion serializer imports
)
from researchhub.settings import PAGINATION_PAGE_SIZE
from researchhub.serializers import DynamicModelFieldSerializer
from user.serializers import MinimalUserSerializer, DynamicUserSerializer
from utils.http import get_user_from_request
# TODO: Make is_public editable for creator as a delete mechanism
# TODO: undo


class CommentSerializerMixin:
    def get_discussion_type(self, obj):
        return Comment.__name__

    def get_unified_document(self, comment):
        from researchhub_document.serializers import (
          DynamicUnifiedDocumentSerializer
        )
        context = self.context
        _context_fields = context.get('dis_dcs_get_unified_document', {})
        serializer = DynamicUnifiedDocumentSerializer(
            comment.unified_document,
            context=context,
            **_context_fields
        )
        return serializer.data

    def _replies_query(self, obj):
        # Optional config to filter child comments
        filter_children = self.context.get('_config', {}).get('filter_replies', None)

        print(filter_children)
        if not filter_children:
            filter_children = {'is_removed': False}

        return self.get_children_annotated(obj, filter_children).order_by(
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


class ThreadSerializerMixin:
    def get_discussion_type(self, obj):
        return Thread.__name__

    def get_user_vote(self, obj):
        user = get_user_from_request(self.context)
        if user and not user.is_anonymous:
            vote = obj.votes.filter(created_by=user)
            if vote.exists():
                return VoteSerializer(vote.last()).data
            return False
        return False

    def get_paper_slug(self, obj):
        if obj.paper:
            return obj.paper.slug

    def get_post_slug(self, obj):
        if obj.post:
            return obj.post.slug

    def get_created_by(self, thread):
        context = self.context
        _context_fields = context.get('dis_dts_get_created_by', {})
        serializer = DynamicUserSerializer(
            thread.created_by,
            context=context,
            **_context_fields
        )
        return serializer.data

    def _comments_query(self, obj):
        # Optional config to filter child comments
        filter_children = self.context.get('_config', {}).get('filter_comments', None)

        if not filter_children:
            filter_children = {'is_removed': False}

        return self.get_children_annotated(obj, filter_children).order_by(
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

    def get_paper(self, thread):
        from paper.serializers import DynamicPaperSerializer

        paper = thread.paper
        if not paper:
            return None

        context = self.context
        _context_fields = context.get('dis_dts_get_paper', {})

        serializer = DynamicPaperSerializer(
            paper,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_post(self, thread):
        from researchhub_document.serializers import (
            DynamicPostSerializer
        )

        post = thread.post
        if not post:
            return None

        context = self.context
        _context_fields = context.get('dis_dts_get_post', {})
        serializer = DynamicPostSerializer(
            thread.post,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_score(self, obj):
        return obj.calculate_score()

    def get_unified_document(self, thread):
        from researchhub_document.serializers import (
          DynamicUnifiedDocumentSerializer
        )
        context = self.context
        _context_fields = context.get('dis_dts_get_unified_document', {})
        serializer = DynamicUnifiedDocumentSerializer(
            thread.unified_document,
            context=context,
            **_context_fields
        )
        return serializer.data    

    def get_comment_count(self, obj):
        return self._comments_query(obj).count()


class ReplySerializerMixin:
    def get_discussion_type(self, obj):
        return Reply.__name__

    def get_unified_document(self, reply):
        from researchhub_document.serializers import (
          DynamicUnifiedDocumentSerializer
        )
        context = self.context
        _context_fields = context.get('dis_drs_get_unified_document', {})
        serializer = DynamicUnifiedDocumentSerializer(
            reply.unified_document,
            context=context,
            **_context_fields
        )
        return serializer.data    

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


class DynamicThreadSerializer(
    DynamicModelFieldSerializer,
    GenericReactionSerializerMixin,
    ThreadSerializerMixin
):

    comment_count = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    paper = serializers.SerializerMethodField()
    post = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    unified_document = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    user_flag = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()
    paper_slug = serializers.SerializerMethodField()
    post_slug = serializers.SerializerMethodField()
    promoted = serializers.SerializerMethodField()
    document_meta = serializers.SerializerMethodField()
    discussion_type = serializers.SerializerMethodField()

    class Meta:
        model = Thread
        fields = '__all__'



class DynamicReplySerializer(
    DynamicModelFieldSerializer,
    GenericReactionSerializerMixin,
    ReplySerializerMixin
):
    unified_document = serializers.SerializerMethodField()
    discussion_type = serializers.SerializerMethodField()

    class Meta:
        model = Reply
        fields = '__all__'


class DynamicCommentSerializer(
    DynamicModelFieldSerializer,
    GenericReactionSerializerMixin,
    CommentSerializerMixin,
):
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
    document_meta = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = '__all__'

class CommentSerializer(
    serializers.ModelSerializer,
    GenericReactionSerializerMixin,
    CommentSerializerMixin,
):
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
    document_meta = serializers.SerializerMethodField()

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
            'promoted',
            'document_meta',
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
            'document_meta',
        ]
        model = Comment


class ThreadSerializer(
    serializers.ModelSerializer,
    GenericReactionSerializerMixin,
    ThreadSerializerMixin,
):
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
    post_slug = serializers.SerializerMethodField()
    promoted = serializers.SerializerMethodField()
    document_meta = serializers.SerializerMethodField()

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
            'hypothesis',
            'citation',
            'id',
            'is_public',
            'is_removed',
            'paper_slug',
            'paper',
            'post_slug',
            'post',
            'plain_text',
            'promoted',
            'score',
            'source',
            'text',
            'title',
            'user_flag',
            'user_vote',
            'was_edited',
            'document_meta',
        ]
        read_only_fields = [
            'is_public',
            'is_removed',
            'score',
            'user_flag',
            'user_vote',
            'document_meta'
        ]
        model = Thread



class SimpleThreadSerializer(ThreadSerializer):
    class Meta:
        fields = [
            'id',
        ]
        model = Thread


class ReplySerializer(
    serializers.ModelSerializer,
    GenericReactionSerializerMixin,
    ReplySerializerMixin
):
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
    document_meta = serializers.SerializerMethodField()

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
            'promoted',
            'document_meta'
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
            'paper_id',
            'document_meta'
        ]
        model = Reply

