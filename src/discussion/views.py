from django.contrib.admin.options import get_content_type_for_model
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from .models import Comment, Thread, Reply, Vote
from .serializers import (
    CommentSerializer,
    ThreadSerializer,
    ReplySerializer,
    VoteSerializer
)
from reputation.permissions import (
    CreateDiscussionComment,
    CreateDiscussionReply,
    CreateDiscussionThread,
    UpvoteDiscussionComment,
    UpvoteDiscussionReply,
    UpvoteDiscussionThread
)


class VoteMixin:

    @action(detail=True, methods=['get'])
    def user_vote(self, request, pk=None):
        item = self.get_object()
        user = request.user
        vote = retrieve_vote(user, item)
        return get_vote_response(vote, 200)

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


class ThreadViewSet(viewsets.ModelViewSet, VoteMixin):
    serializer_class = ThreadSerializer

    # Optional attributes
    permission_classes = [IsAuthenticatedOrReadOnly & CreateDiscussionThread]

    def get_queryset(self):
        paper_id = get_paper_id_from_path(self.request)
        threads = Thread.objects.filter(paper=paper_id)
        return threads

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
    )
    def downvote(self, *args, **kwargs):
        return super().downvote(*args, **kwargs)


class CommentViewSet(viewsets.ModelViewSet, VoteMixin):
    serializer_class = CommentSerializer

    permission_classes = [IsAuthenticatedOrReadOnly & CreateDiscussionComment]

    def get_queryset(self):
        thread_id = get_thread_id_from_path(self.request)
        comments = Comment.objects.filter(parent=thread_id)
        return comments

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
    )
    def downvote(self, *args, **kwargs):
        return super().downvote(*args, **kwargs)


class ReplyViewSet(viewsets.ModelViewSet, VoteMixin):
    serializer_class = ReplySerializer

    permission_classes = [IsAuthenticatedOrReadOnly & CreateDiscussionReply]

    def get_queryset(self):
        comment_id = get_comment_id_from_path(self.request)
        comment = Comment.objects.first()
        replies = Reply.objects.filter(
            content_type=get_content_type_for_model(comment),
            object_id=comment_id
        )
        return replies

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
        vote.save()
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
