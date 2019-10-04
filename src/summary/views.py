from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Summary
from .serializers import SummarySerializer
from paper.models import Paper

class SummaryViewSet(viewsets.ModelViewSet):
    queryset = Summary.objects.all()
    serializer_class = SummarySerializer
    
    permission_classes = [IsAuthenticatedOrReadOnly]

    @action(detail=False, methods=['post'])
    def propose_edit(self, request):
        summary = request.data.get('summary')
        paper_id = request.data.get('paper')
        previous_summary_id = request.data.get('previousSummaryId')

        new_summary = Summary.objects.create(
            summary=summary,
            proposed_by=request.user,
            paper_id=paper_id,
        )
        if previous_summary_id:
            previous_summary = Summary.objects.get(id=previous_summary_id)
            previous_summary.save()
            new_summary.previous = previous_summary
            new_summary.save()

        paper = Paper.objects.get(id=paper_id)
        paper.summary = new_summary
        paper.save()
        return Response(SummarySerializer(new_summary).data, status=200)

    @action(detail=False, methods=['post'])
    def get_edits(self, request):
        paper_id = request.data.get('paper')

        summary_queryset = Summary.objects.filter(paper_id=paper_id, approved=True).order_by('-approved_at')
        summary = SummarySerializer(summary_queryset, many=True).data

        return Response(summary, status=200)