from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from .models import Comment, Thread, Vote
from .serializers import CommentSerializer, ThreadSerializer, VoteSerializer
from reputation.permissions import (
    CreateDiscussionThread,
    UpvoteDiscussionComment,
    UpvoteDiscussionThread,
)


class ThreadViewSet(viewsets.ModelViewSet):
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
    def upvote(self, request, pk=None):
        item = self.get_object()
        vote = Vote.objects.update_or_create(
                created_by=request.user,
                item=item,
                vote_type=Vote.UPVOTE,
        )
        serializer = VoteSerializer(vote)
        if serializer.is_valid():
            return serializer.data
        else:
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )


class CommentViewSet(viewsets.ModelViewSet):
    serializer_class = CommentSerializer

    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        thread_id = get_thread_id_from_path(self.request)
        comments = Comment.objects.filter(parent=thread_id)
        return comments

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[UpvoteDiscussionComment]
    )
    def upvote(self, request, pk=None):
        pass


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
            print('Failed to get paper id')
    return thread_id
