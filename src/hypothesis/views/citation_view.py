from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from discussion.reaction_views import ReactionViewActionMixin
from hypothesis.models import Citation
from hypothesis.serializers import CitationSerializer


class CitationViewSet(ModelViewSet, ReactionViewActionMixin):
    ordering = ('-created_date')
    queryset = Citation.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    serializer_class = CitationSerializer

    def create(self, request, *args, **kwargs):
        hypothesis_id = request.data.get('hypothesis')
        source_id = request.data.get('source')

        citation = Citation.objects.create(
            created_by=request.user,
            hypothesis_id=hypothesis_id,
            source_id=source_id,
        )
        serializer = self.serializer_class(citation)
        return Response(serializer.data, status=200)
