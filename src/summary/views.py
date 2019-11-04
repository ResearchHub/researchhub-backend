from django.db import transaction
from rest_framework import viewsets
from rest_framework.permissions import (
    IsAuthenticated,
    IsAuthenticatedOrReadOnly
)
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Summary
from .permissions import ProposeSummaryEdit, UpdateOrDeleteSummaryEdit
from .serializers import SummarySerializer
from paper.models import Paper

# TODO: Add flagging actions and permissions


class SummaryViewSet(viewsets.ModelViewSet):
    queryset = Summary.objects.all()
    serializer_class = SummarySerializer

    permission_classes = [
        IsAuthenticatedOrReadOnly
        & ProposeSummaryEdit
        & UpdateOrDeleteSummaryEdit
    ]

    @action(detail=False, methods=['get'])
    def get_edit_history(self, request):
        paper_id = request.GET['paperId']

        summary_queryset = Summary.objects.filter(
            paper_id=paper_id,
            approved=True
        ).order_by('-approved_date')
        summary = SummarySerializer(summary_queryset, many=True).data

        return Response(summary, status=200)

    @transaction.atomic
    def create(self, request):
        paper_id = request.data.get('paper')
        summary = self._create_summary(request)

        if self._user_can_direct_edit(request.user):
            self._approve_and_add_summary_to_paper(
                paper_id,
                summary,
                request.user
            )

        return Response(SummarySerializer(summary).data, status=201)

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

                return Response(
                    SummarySerializer(summary).data,
                    status=201
                )

    @transaction.atomic
    def _create_summary(self, request):
        user = request.user
        summary = request.data.get('summary')
        paper_id = request.data.get('paper')
        previous_summary_id = request.data.get('previousSummaryId', None)

        previous_summary = None
        if previous_summary_id is not None:
            previous_summary = Summary.objects.get(id=previous_summary_id)

        new_summary = Summary.objects.create(
            summary=summary,
            proposed_by=user,
            paper_id=paper_id,
            previous=previous_summary
        )

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
