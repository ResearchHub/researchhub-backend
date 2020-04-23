from django.core.cache import cache
from django.contrib.admin.options import get_content_type_for_model
from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import (
    IsAuthenticatedOrReadOnly,
    IsAuthenticated
)
from rest_framework.response import Response

from discussion.models import Comment, Endorsement, Flag, Thread, Reply, Vote
from .serializers import (
    CommentSerializer,
    EndorsementSerializer,
    FlagSerializer,
    ThreadSerializer,
    ReplySerializer,
    VoteSerializer
)
from discussion.permissions import (
    CensorDiscussion,
    CreateDiscussionComment,
    CreateDiscussionReply,
    CreateDiscussionThread,
    Endorse,
    FlagDiscussionComment,
    FlagDiscussionReply,
    FlagDiscussionThread,
    UpdateDiscussionComment,
    UpdateDiscussionReply,
    UpdateDiscussionThread,
    UpvoteDiscussionComment,
    UpvoteDiscussionReply,
    UpvoteDiscussionThread,
    DownvoteDiscussionComment,
    DownvoteDiscussionReply,
    DownvoteDiscussionThread,
    Vote as VotePermission
)
from paper.models import Paper
from paper.utils import get_cache_key
from .utils import (
    get_comment_id_from_path,
    get_paper_id_from_path,
    get_thread_id_from_path
)


class ActionMixin:

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[Endorse]
    )
    def endorse(self, request, pk=None):
        item = self.get_object()
        user = request.user

        try:
            endorsement = create_endorsement(user, item)
            serialized = EndorsementSerializer(endorsement)
            return Response(serialized.data, status=201)
        except Exception as e:
            return Response(
                f'Failed to create endorsement: {e}',
                status=status.HTTP_400_BAD_REQUEST
            )

    @endorse.mapping.delete
    def delete_endorse(self, request, pk=None):
        item = self.get_object()
        user = request.user
        try:
            endorsement = retrieve_endorsement(user, item)
            endorsement_id = endorsement.id
            endorsement.delete()
            return Response(endorsement_id, status=200)
        except Exception as e:
            return Response(
                f'Failed to delete endorsement: {e}',
                status=400
            )

    def flag(self, request, pk=None):
        item = self.get_object()
        user = request.user
        reason = request.data.get('reason')

        try:
            flag = create_flag(user, item, reason)
            serialized = FlagSerializer(flag)
            return Response(serialized.data, status=201)
        except Exception as e:
            return Response(
                f'Failed to create flag: {e}',
                status=status.HTTP_400_BAD_REQUEST
            )

    def delete_flag(self, request, pk=None):
        item = self.get_object()
        user = request.user
        try:
            flag = retrieve_flag(user, item)
            serialized = FlagSerializer(flag)
            flag.delete()
            return Response(serialized.data, status=200)
        except Exception as e:
            return Response(
                f'Failed to delete flag: {e}',
                status=400
            )

    @action(
        detail=True,
        methods=['put', 'patch', 'delete'],
        permission_classes=[IsAuthenticated, CensorDiscussion]
    )
    def censor(self, request, pk=None):
        item = self.get_object()
        item.is_removed = True
        item.save()
        return Response(
            self.get_serializer(instance=item).data,
            status=200
        )

    def upvote(self, request, pk=None):
        item = self.get_object()
        user = request.user

        vote_exists = find_vote(user, item, Vote.UPVOTE)

        if vote_exists:
            return Response(
                'This vote already exists',
                status=status.HTTP_400_BAD_REQUEST
            )
        response = update_or_create_vote(user, item, Vote.UPVOTE)
        return response

    def downvote(self, request, pk=None):
        item = self.get_object()
        user = request.user

        vote_exists = find_vote(user, item, Vote.DOWNVOTE)

        if vote_exists:
            return Response(
                'This vote already exists',
                status=status.HTTP_400_BAD_REQUEST
            )
        response = update_or_create_vote(user, item, Vote.DOWNVOTE)
        return response

    @action(detail=True, methods=['get'])
    def user_vote(self, request, pk=None):
        item = self.get_object()
        user = request.user
        vote = retrieve_vote(user, item)
        return get_vote_response(vote, 200)

    @user_vote.mapping.delete
    def delete_user_vote(self, request, pk=None):
        try:
            item = self.get_object()
            user = request.user
            vote = retrieve_vote(user, item)
            vote_id = vote.id
            vote.delete()
            return Response(vote_id, status=200)
        except Exception as e:
            return Response(f'Failed to delete vote: {e}', status=400)

    def get_ordering(self):
        default_ordering = ['-created_date',]
        if self.ordering:
            default_ordering = self.ordering
        ordering = self.request.query_params.get('ordering', default_ordering)
        if isinstance(ordering, str):
            if ordering and 'created_date' not in ordering:
                ordering = [ordering, '-created_date']
            elif 'created_date' not in ordering:
                ordering = ['-created_date']
            else:
                ordering = [ordering]
        return ordering

    def get_action_context(self):
        ordering = self.get_ordering()
        needs_score = False
        if 'score' in ordering or '-score' in ordering:
            needs_score = True
        return {
            'ordering': ordering,
            'needs_score': needs_score,
        }


class ThreadViewSet(viewsets.ModelViewSet, ActionMixin):
    serializer_class = ThreadSerializer

    # Optional attributes
    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreateDiscussionThread
        & UpdateDiscussionThread
    ]
    filter_backends = (OrderingFilter,)
    order_fields = '__all__'
    ordering = ('-created_date',)

    def create(self, *args, **kwargs):
        response = super().create(*args, **kwargs)
        paper_id = get_paper_id_from_path(args[0])
        hubs = list(Paper.objects.get(
            id=paper_id
        ).hubs.values_list('id', flat=True)) + [0]

        for hub_id in hubs:
            cache_key = get_cache_key(
                None,
                'hub',
                pk=f'{hub_id}_-discussed_week'
            )
            cache.delete(cache_key)
        return response

    def get_serializer_context(self):
        return {**super().get_serializer_context(), **self.get_action_context(), 'needs_score': True}

    def filter_queryset(self, *args, **kwargs):
        return super().filter_queryset(*args, **kwargs).order_by(*self.get_ordering())

    def get_queryset(self):
        upvotes = Count('votes', filter=Q(votes__vote_type=Vote.UPVOTE,))
        downvotes = Count('votes', filter=Q(votes__vote_type=Vote.DOWNVOTE,))
        paper_id = get_paper_id_from_path(self.request)
        threads = Thread.objects.filter(paper=paper_id).annotate(score=upvotes-downvotes)
        return threads

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[FlagDiscussionThread]
    )
    def flag(self, *args, **kwargs):
        return super().flag(*args, **kwargs)

    @flag.mapping.delete
    def delete_flag(self, *args, **kwargs):
        return super().delete_flag(*args, **kwargs)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[UpvoteDiscussionThread & VotePermission]
    )
    def upvote(self, *args, **kwargs):
        return super().upvote(*args, **kwargs)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[DownvoteDiscussionThread & VotePermission]
    )
    def downvote(self, *args, **kwargs):
        return super().downvote(*args, **kwargs)


class CommentViewSet(viewsets.ModelViewSet, ActionMixin):
    serializer_class = CommentSerializer

    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreateDiscussionComment
        & UpdateDiscussionComment
    ]

    filter_backends = (OrderingFilter,)
    order_fields = '__all__'
    ordering = ('-created_date',)

    def get_queryset(self):
        thread_id = get_thread_id_from_path(self.request)
        comments = Comment.objects.filter(
            parent=thread_id
        ).order_by('-created_date')
        return comments

    def create(self, *args, **kwargs):
        response = super().create(*args, **kwargs)
        paper_id = get_paper_id_from_path(args[0])
        hubs = list(Paper.objects.get(
            id=paper_id
        ).hubs.values_list('id', flat=True)) + [0]

        for hub_id in hubs:
            cache_key = get_cache_key(
                None,
                'hub',
                pk=f'{hub_id}_-discussed_week'
            )
            cache.delete(cache_key)
        return response

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[FlagDiscussionComment]
    )
    def flag(self, *args, **kwargs):
        return super().flag(*args, **kwargs)

    @flag.mapping.delete
    def delete_flag(self, *args, **kwargs):
        return super().delete_flag(*args, **kwargs)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[UpvoteDiscussionComment & VotePermission]
    )
    def upvote(self, *args, **kwargs):
        return super().upvote(*args, **kwargs)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[DownvoteDiscussionComment & VotePermission]
    )
    def downvote(self, *args, **kwargs):
        return super().downvote(*args, **kwargs)


class ReplyViewSet(viewsets.ModelViewSet, ActionMixin):
    serializer_class = ReplySerializer

    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreateDiscussionReply
        & UpdateDiscussionReply
    ]

    filter_backends = (OrderingFilter,)
    order_fields = '__all__'
    ordering = ('-created_date',)

    def get_queryset(self):
        comment_id = get_comment_id_from_path(self.request)
        comment = Comment.objects.first()
        replies = Reply.objects.filter(
            content_type=get_content_type_for_model(comment),
            object_id=comment_id
        ).order_by('-created_date')
        return replies

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[FlagDiscussionReply]
    )
    def flag(self, *args, **kwargs):
        return super().flag(*args, **kwargs)

    @flag.mapping.delete
    def delete_flag(self, *args, **kwargs):
        return super().delete_flag(*args, **kwargs)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[UpvoteDiscussionReply & VotePermission]
    )
    def upvote(self, *args, **kwargs):
        return super().upvote(*args, **kwargs)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[DownvoteDiscussionReply & VotePermission]
    )
    def downvote(self, *args, **kwargs):
        return super().downvote(*args, **kwargs)


def retrieve_endorsement(user, item):
    return Endorsement.objects.get(
        object_id=item.id,
        content_type=get_content_type_for_model(item),
        created_by=user.id
    )


def create_endorsement(user, item):
    endorsement = Endorsement(created_by=user, item=item)
    endorsement.save()
    return endorsement


def retrieve_flag(user, item):
    return Flag.objects.get(
        object_id=item.id,
        content_type=get_content_type_for_model(item),
        created_by=user.id
    )


def create_flag(user, item, reason):
    flag = Flag(created_by=user, item=item, reason=reason)
    flag.save()
    return flag


def find_vote(user, item, vote_type):
    vote = Vote.objects.filter(
        object_id=item.id,
        content_type=get_content_type_for_model(item),
        created_by=user,
        vote_type=vote_type
    )
    if vote:
        return True
    return False


def update_or_create_vote(user, item, vote_type):
    vote = retrieve_vote(user, item)

    if vote:
        vote.vote_type = vote_type
        vote.save(update_fields=['updated_date', 'vote_type'])
        return get_vote_response(vote, 200)
    vote = create_vote(user, item, vote_type)
    return get_vote_response(vote, 201)


def get_vote_response(vote, status_code):
    serializer = VoteSerializer(vote)
    return Response(serializer.data, status=status_code)


def retrieve_vote(user, item):
    try:
        return Vote.objects.get(
            object_id=item.id,
            content_type=get_content_type_for_model(item),
            created_by=user.id
        )
    except Vote.DoesNotExist:
        return None


def create_vote(user, item, vote_type):
    vote = Vote(created_by=user, item=item, vote_type=vote_type)
    vote.save()
    return vote
