from django.contrib.admin.options import get_content_type_for_model
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from .models import Comment, Flag, Thread, Reply, Vote
from .serializers import (
    CommentSerializer,
    FlagSerializer,
    ThreadSerializer,
    ReplySerializer,
    VoteSerializer
)
from .permissions import (
    CreateDiscussionComment,
    CreateDiscussionReply,
    CreateDiscussionThread,
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
    DownvoteDiscussionThread
)

# TODO: Add permission to only delete your own flag


class ActionMixin:

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
        error = None

        item = self.get_object()
        user = request.user
        flag = retrieve_flag(user, item)

        if flag is not None:
            try:
                serialized = FlagSerializer(flag)
                flag.delete()
                return Response(serialized.data, status=200)
            except Exception as e:
                error = e
        else:
            error = Flag.DoesNotExist

        return Response(
            f'Failed to delete flag: {error}',
            status=400
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


class ThreadViewSet(viewsets.ModelViewSet, ActionMixin):
    serializer_class = ThreadSerializer

    # Optional attributes
    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreateDiscussionThread
        & UpdateDiscussionThread
    ]

    def get_queryset(self):
        paper_id = get_paper_id_from_path(self.request)
        threads = Thread.objects.filter(paper=paper_id)
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
        permission_classes=[UpvoteDiscussionThread]
    )
    def upvote(self, *args, **kwargs):
        return super().upvote(*args, **kwargs)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[DownvoteDiscussionThread]
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

    def get_queryset(self):
        thread_id = get_thread_id_from_path(self.request)
        comments = Comment.objects.filter(
            parent=thread_id
        ).order_by('-created_date')
        return comments

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
        permission_classes=[UpvoteDiscussionComment]
    )
    def upvote(self, *args, **kwargs):
        return super().upvote(*args, **kwargs)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[DownvoteDiscussionComment]
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
        permission_classes=[UpvoteDiscussionReply]
    )
    def upvote(self, *args, **kwargs):
        return super().upvote(*args, **kwargs)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[DownvoteDiscussionReply]
    )
    def downvote(self, *args, **kwargs):
        return super().downvote(*args, **kwargs)


def get_paper_id_from_path(request):
    PAPER = 2
    paper_id = None
    path_parts = request.path.split('/')
    if path_parts[PAPER] == 'paper':
        try:
            paper_id = int(path_parts[PAPER + 1])
        except ValueError:
            print('Failed to get paper id')
    return paper_id


def get_thread_id_from_path(request):
    DISCUSSION = 4
    thread_id = None
    path_parts = request.path.split('/')
    if path_parts[DISCUSSION] == 'discussion':
        try:
            thread_id = int(path_parts[DISCUSSION + 1])
        except ValueError:
            print('Failed to get discussion id')
    return thread_id


def get_comment_id_from_path(request):
    COMMENT = 6
    comment_id = None
    path_parts = request.path.split('/')
    if path_parts[COMMENT] == 'comment':
        try:
            comment_id = int(path_parts[COMMENT + 1])
        except ValueError:
            print('Failed to get comment id')
    return comment_id


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


def retrieve_flag(user, item):
    try:
        return Flag.objects.get(
            object_id=item.id,
            content_type=get_content_type_for_model(item),
            created_by=user.id
        )
    except Flag.DoesNotExist:
        return None


def create_flag(user, item, reason):
    flag = Flag(created_by=user, item=item, reason=reason)
    flag.save()
    return flag
