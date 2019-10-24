from django.db import transaction
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly
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
        ).order_by('-approved_at')
        summary = SummarySerializer(summary_queryset, many=True).data

        return Response(summary, status=200)

    @transaction.atomic
    def create(self, request):
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

        if self._user_can_direct_edit(user):
            new_summary.approve(by=user)
            self._set_paper_summary(new_summary)

        return Response(SummarySerializer(new_summary).data, status=201)

    def _user_can_direct_edit(self, user):
        return user.reputation >= 50

    def _set_paper_summary(self, paper_id, summary):
        paper = Paper.objects.get(id=paper_id)
        paper.update_summary(summary)
