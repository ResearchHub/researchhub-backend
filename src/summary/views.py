from django.core.cache import cache
from django.db import transaction
from rest_framework import viewsets
from rest_framework.permissions import (
    IsAuthenticated,
    IsAuthenticatedOrReadOnly
)
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status

from .models import Summary, Vote
from .permissions import ProposeSummaryEdit, UpdateOrDeleteSummaryEdit
from .serializers import SummarySerializer, SummaryVoteSerializer
from paper.models import Paper
from paper.utils import get_cache_key
from reputation.models import Contribution
from reputation.tasks import create_contribution
from utils.permissions import CreateOrUpdateIfAllowed
from utils.throttles import THROTTLE_CLASSES
from utils.siftscience import events_api, update_user_risk_score
# TODO: Add flagging actions and permissions


class SummaryViewSet(viewsets.ModelViewSet):
    queryset = Summary.objects.all()
    serializer_class = SummarySerializer

    throttle_classes = THROTTLE_CLASSES
    permission_classes = [
        IsAuthenticatedOrReadOnly
        & ProposeSummaryEdit
        & UpdateOrDeleteSummaryEdit
        & CreateOrUpdateIfAllowed
    ]

    def _invalidate_paper_cache(self, paper_id):
        cache_key = get_cache_key(None, 'paper', pk=paper_id)
        cache.delete(cache_key)

    @action(detail=False, methods=['get'])
    def get_edit_history(self, request):
        paper_id = request.GET['paperId']

        summary_queryset = Summary.objects.filter(
            paper_id=paper_id,
            approved=True
        ).order_by('-approved_date')

        page = self.paginate_queryset(summary_queryset)
        context = self.get_serializer_context()

        if page is not None:
            serializer = SummarySerializer(page, context=context, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(page, context=context, many=True)
        return Response(serializer.data, status=200)

    @transaction.atomic
    def create(self, request):
        paper_id = request.data.get('paper')
        summary = self._create_summary(request)
        context = self.get_serializer_context()

        if self._user_can_direct_edit(request.user):
            self._approve_and_add_summary_to_paper(
                paper_id,
                summary,
                request.user
            )
        self._invalidate_paper_cache(paper_id)
        update_or_create_vote(request, request.user, summary, Vote.UPVOTE)
        data = SummarySerializer(summary, context=context).data
        create_contribution.apply_async(
            (
                Contribution.CURATOR,
                {'app_label': 'summary', 'model': 'summary'},
                request.user.id,
                paper_id,
                summary.id
            ),
            priority=2,
            countdown=10
        )
        return Response(data, status=201)

    @action(
        detail=False,
        methods=['post'],
        permission_classes=[IsAuthenticated]
    )
    def first(self, request):
        paper_id = request.data.get('paper')

        try:
            paper = Paper.objects.get(pk=paper_id)
        except Paper.DoesNotExist:
            return Response(
                f'Failed to get paper with id {paper_id}',
                status=400
            )

        if request.user != paper.uploaded_by:
            return Response(
                'Summary paper must be uploaded by request user',
                status=403
            )
        else:
            with transaction.atomic():
                summary = self._create_summary(request)

                if self._paper_has_no_summary(paper_id):
                    # approved_by = None denotes the paper's first summary
                    approved_by = None
                    self._approve_and_add_summary_to_paper(
                        paper_id,
                        summary,
                        approved_by
                    )
                    self._invalidate_paper_cache(paper_id)

                return Response(
                    SummarySerializer(summary).data,
                    status=201
                )

    @transaction.atomic
    def _create_summary(self, request):
        # TODO: Should we fail if they don't provide the previous summary?
        # Or just grab the last paper summary created and set it to previous?
        user = request.user
        summary = request.data.get('summary')
        paper_id = request.data.get('paper')
        summary_plain_text = request.data.get('summary_plain_text', '')
        previous_summary_id = request.data.get('previousSummaryId', None)

        created_location = None
        if request.query_params.get('created_location') == 'progress':
            created_location = Summary.CREATED_LOCATION_PROGRESS

        previous_summary = None
        if previous_summary_id is not None:
            previous_summary = Summary.objects.get(id=previous_summary_id)

        new_summary = Summary.objects.create(
            summary=summary,
            summary_plain_text=summary_plain_text,
            proposed_by=user,
            paper_id=paper_id,
            previous=previous_summary,
            created_location=created_location
        )

        tracked_summary = events_api.track_content_summary(user, new_summary, request, update=bool(previous_summary))
        update_user_risk_score(user, tracked_summary)

        return new_summary

    def _paper_has_no_summary(self, paper_id):
        paper = Paper.objects.get(id=paper_id)
        return paper.summary is None

    def _user_can_direct_edit(self, user):
        return user.reputation >= 50

    def _approve_and_add_summary_to_paper(self, paper_id, summary, user):
        summary.approve(by=user)
        summary.save()
        self._update_paper_summary(paper_id, summary)

    def _update_paper_summary(self, paper_id, summary):
        paper = Paper.objects.get(id=paper_id)
        paper.update_summary(summary)
        paper.save()
        self._invalidate_paper_cache(paper_id)

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[
            CreateOrUpdateIfAllowed
        ]
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
        response = update_or_create_vote(request, user, item, Vote.UPVOTE)
        return response

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[
            CreateOrUpdateIfAllowed
        ]
    )
    def downvote(self, request, pk=None):
        item = self.get_object()
        user = request.user

        vote_exists = find_vote(user, item, Vote.DOWNVOTE)

        if vote_exists:
            return Response(
                'This vote already exists',
                status=status.HTTP_400_BAD_REQUEST
            )
        response = update_or_create_vote(request, user, item, Vote.DOWNVOTE)
        return response

    @action(
        detail=False,
        methods=['get'],
    )
    def check_user_vote(self, request):
        summary_ids = request.query_params['summary_ids'].split(',')
        user = request.user
        response = {}

        if user.is_authenticated:
            votes = Vote.objects.filter(
                summary__id__in=summary_ids,
                created_by=user
            )

            for vote in votes.iterator():
                summary = vote.summary
                summary_id = summary.id
                data = SummaryVoteSerializer(instance=vote).data
                score = SummarySerializer().get_score(summary)
                data['score'] = score
                response[summary_id] = data

        return Response(response, status=status.HTTP_200_OK)


def create_vote(user, summary, vote_type):
    vote = Vote(
        created_by=user,
        summary=summary,
        vote_type=vote_type
    )
    vote.save()
    return vote


def find_vote(user, summary, vote_type):
    vote = Vote.objects.filter(
        summary=summary,
        created_by=user,
        vote_type=vote_type
    )
    if vote:
        return True
    return False


def retrieve_vote(user, summary):
    try:
        return Vote.objects.get(
            summary=summary,
            created_by=user.id
        )
    except Vote.DoesNotExist:
        return None


def get_vote_response(vote, status_code):
    serializer = SummaryVoteSerializer(vote)
    return Response(serializer.data, status=status_code)


def update_or_create_vote(request, user, summary, vote_type):
    vote = retrieve_vote(user, summary)

    if vote:
        vote.vote_type = vote_type
        vote.save(update_fields=['updated_date', 'vote_type'])
        events_api.track_content_vote(user, vote, request)
        return get_vote_response(vote, 200)

    vote = create_vote(user, summary, vote_type)
    events_api.track_content_vote(user, vote, request)
    create_contribution.apply_async(
        (
            Contribution.UPVOTER,
            {'app_label': 'summary', 'model': 'vote'},
            user.id,
            summary.paper.id,
            vote.id
        ),
        priority=3,
        countdown=10
    )
    return get_vote_response(vote, 201)
