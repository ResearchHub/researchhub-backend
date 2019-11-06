from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from .filters import *
from .models import Flag, Paper, Vote
from .permissions import (
    CreatePaper,
    FlagPaper,
    IsAuthor,
    UpdatePaper,
    UpvotePaper,
    DownvotePaper
)
from .serializers import FlagSerializer, PaperSerializer, VoteSerializer

import datetime

class PaperViewSet(viewsets.ModelViewSet):
    queryset = Paper.objects.all()
    serializer_class = PaperSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    search_fields = ('title', 'doi')
    filter_class = PaperFilter
    ordering = ('-uploaded_date')

    # Optional attributes
    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreatePaper
        & UpdatePaper
    ]

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[IsAuthor]
    )
    def assign_moderator(self, request, pk=None):
        '''Assign users as paper moderators'''
        paper = self.get_object()
        moderators = request.data.get('moderators')
        if not isinstance(moderators, list):
            moderators = [moderators]
        paper.moderators.add(*moderators)
        paper.save()
        return Response(PaperSerializer(paper).data)

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[FlagPaper]  # Also applies to delete_flag below
    )
    def flag(self, request, pk=None):
        paper = self.get_object()
        reason = request.data.get('reason')
        flag = Flag.objects.create(
            paper=paper,
            created_by=request.user,
            reason=reason
        )
        return Response(FlagSerializer(flag).data, status=201)

    @flag.mapping.delete
    def delete_flag(self, request, pk=None):
        try:
            flag = Flag.objects.get(
                paper=pk,
                created_by=request.user.id
            )
            flag_id = flag.id
            flag.delete()
            return Response(flag_id, status=200)
        except Exception as e:
            return Response(f'Failed to delete flag: {e}', status=400)

    @action(detail=True, methods=['get'])
    def user_vote(self, request, pk=None):
        paper = self.get_object()
        user = request.user
        vote = retrieve_vote(user, paper)
        return get_vote_response(vote, 200)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[UpvotePaper]
    )
    def upvote(self, request, pk=None):
        paper = self.get_object()
        user = request.user

        vote_exists = find_vote(user, paper, Vote.UPVOTE)

        if vote_exists:
            return Response(
                'This vote already exists',
                status=status.HTTP_400_BAD_REQUEST
            )
        response = update_or_create_vote(user, paper, Vote.UPVOTE)
        return response

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[DownvotePaper]
    )
    def downvote(self, request, pk=None):
        paper = self.get_object()
        user = request.user

        vote_exists = find_vote(user, paper, Vote.DOWNVOTE)

        if vote_exists:
            return Response(
                'This vote already exists',
                status=status.HTTP_400_BAD_REQUEST
            )
        response = update_or_create_vote(user, paper, Vote.DOWNVOTE)
        return response

    @action(
        detail=False,
        methods=['get'],
    )
    def get_hub_papers(self, request):
        def most_discussed_sort(paper):
            discussions = paper.threads.all()
            total_discussed = len(discussions)
            comments = []
            for discussion in discussions:
                total_discussed = total_discussed + discussion.comments.count()
                comments = comments + list(discussion.comments.all())

            for comment in comments:
                total_discussed = total_discussed + comment.replies.count()

            print(total_discussed)
            return total_discussed

        uploaded_start = datetime.datetime.fromtimestamp(int(request.GET["uploaded_date__gte"]))
        uploaded_end = datetime.datetime.fromtimestamp(int(request.GET["uploaded_date__lte"]))
        ordering = request.GET['ordering']
        hub_id = request.GET["hub_id"]
        if int(hub_id) == 0:
            papers = Paper.objects.filter(
                uploaded_date__gte=uploaded_start,
                uploaded_date__lte=uploaded_end
            )
        else:
            papers = Paper.objects.filter(
                hubs=hub_id,
                uploaded_date__gte=uploaded_start,
                uploaded_date__lte=uploaded_end
            )

        order_papers = papers

        if ordering == 'newest':
            order_papers = papers.order_by("-uploaded_date")
        elif ordering == "top_rated":
            order_papers = papers.order_by()
        elif ordering == "most_discussed":
            order_papers = list(order_papers)
            order_papers.sort(key=most_discussed_sort, reverse=True)

        page = self.paginate_queryset(order_papers)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

def find_vote(user, paper, vote_type):
    vote = Vote.objects.filter(
        paper=paper,
        created_by=user,
        vote_type=vote_type
    )
    if vote:
        return True
    return False

def update_or_create_vote(user, paper, vote_type):
    vote = retrieve_vote(user, paper)

    if vote:
        vote.vote_type = vote_type
        vote.save()
        return get_vote_response(vote, 200)
    vote = create_vote(user, paper, vote_type)
    return get_vote_response(vote, 201)

def get_vote_response(vote, status_code):
    serializer = VoteSerializer(vote)
    return Response(serializer.data, status=status_code)

def retrieve_vote(user, paper):
    try:
        return Vote.objects.get(
            paper=paper,
            created_by=user.id
        )
    except Vote.DoesNotExist:
        return None

def create_vote(user, paper, vote_type):
    vote = Vote.objects.create(
        created_by=user,
        paper=paper,
        vote_type=vote_type
    )
    return vote
