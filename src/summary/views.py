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
        previous_summary = Summary.objects.get(id=previous_summary_id)
        previous_summary.save()

        new_summary = Summary.objects.create(
            summary=summary,
            proposed_by=request.user,
            paper_id=paper_id,
        )

        new_summary.previous = previous_summary
        new_summary.save()

        paper = Paper.objects.get(id=paper_id)
        paper.summary = new_summary
        paper.save()

        return Response(status=200)

