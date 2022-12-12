from rest_framework.exceptions import ParseError
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from utils import sentry

from discussion.reaction_views import ReactionViewActionMixin
from hypothesis.models import Citation, Hypothesis
from hypothesis.serializers import CitationSerializer


class CitationViewSet(ModelViewSet, ReactionViewActionMixin):
    ordering = ('-created_date')
    queryset = Citation.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    serializer_class = CitationSerializer

    def create(self, request, *args, **kwargs):
        request_data = request.data
        hypothesis_id = request_data.get('hypothesis_id')
        source_id = request_data.get('source_id') # source is equivalent to unifiedDocID
        try:
            if (hypothesis_id is None or source_id is None):
                raise ParseError(
                    f'Invalid payload hypothesis_id: {hypothesis_id}, \
                        source_id: ${source_id}'
                )

            citation = Citation.objects.create(
                created_by=request.user,
                source_id=source_id,
                citation_type=request_data.get('citation_type'),
            )
            citation.hypothesis.set([
                Hypothesis.objects.get(id=hypothesis_id)
            ])
            citation.save()
            serializer = self.serializer_class(citation)
            return Response(serializer.data, status=200)
        except Exception as error:
            sentry.log_error(error)
            return Response(error, status=400)
