from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Summary
from .permissions import CreateSummary, ProposeSummaryEdit
from .serializers import SummarySerializer
from paper.models import Paper


class SummaryViewSet(viewsets.ModelViewSet):
    queryset = Summary.objects.all()
    serializer_class = SummarySerializer

    permission_classes = [IsAuthenticatedOrReadOnly]

    @action(detail=False, methods=['get'])
    def get_edit_history(self, request):
        paper_id = request.GET['paperId']

        summary_queryset = Summary.objects.filter(
            paper_id=paper_id,
            approved=True
        ).order_by('-approved_at')
        summary = SummarySerializer(summary_queryset, many=True).data

        return Response(summary, status=200)

    # TODO: Make this atomic and respond with failure message if it throws
    @action(
        detail=False,
        methods=['post'],
        permission_classes=[ProposeSummaryEdit]
    )
    def propose_edit(self, request):
        user = request.user
        summary = request.data.get('summary')
        paper_id = request.data.get('paper')
        previous_summary_id = request.data.get('previousSummaryId')

        previous_summary = None

        if previous_summary_id:
            previous_summary = Summary.objects.get(id=previous_summary_id)
            # previous_summary.save()
            # new_summary.previous = previous_summary
            # new_summary.save()

        new_summary = Summary.objects.create(
            summary=summary,
            proposed_by=user,
            paper_id=paper_id,
            previous=previous_summary,
        )

        if self._user_can_direct_edit(user):
            new_summary.approve(by=user)
            self._update_paper_summary(new_summary)

        return Response(SummarySerializer(new_summary).data, status=201)

    def _user_can_direct_edit(self, user):
        return user.reputation >= 50

    def _update_paper_summary(self, paper_id, summary):
        paper = Paper.objects.get(id=paper_id)
        paper.update_summary(summary)
