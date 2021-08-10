from rest_framework.permissions import (
    IsAuthenticated,
    IsAuthenticatedOrReadOnly
)
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action

from discussion.reaction_views import ReactionViewActionMixin
from hub.models import Hub
from hypothesis.models import Hypothesis
from hypothesis.serializers import (
    HypothesisSerializer,
    DynamicCitationSerializer
)
from researchhub_document.models import (
    ResearchhubUnifiedDocument
)
from researchhub_document.related_models.constants.document_type import (
    HYPOTHESIS
)


class HypothesisViewSet(ModelViewSet, ReactionViewActionMixin):
    ordering = ('-created_date')
    queryset = Hypothesis.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    serializer_class = HypothesisSerializer

    def create(self, request, *args, **kwargs):
        data = request.data
        title = data.get('title', '')
        unified_doc = self._create_unified_doc(request)
        hypo = Hypothesis.objects.create(
            created_by=request.user,
            title=title,
            unified_document=unified_doc
        )
        serializer = HypothesisSerializer(hypo)
        data = serializer.data
        return Response(data, status=200)

    def _create_unified_doc(self, request):
        data = request.data
        hubs = Hub.objects.filter(
            id__in=data.get('hubs', [])
        ).all()
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=HYPOTHESIS,
        )
        unified_doc.hubs.add(*hubs)
        unified_doc.save()
        return unified_doc

    @action(detail=True, methods=['get'])
    def get_citations(self, request, pk=None):
        hypothesis = self.get_object()
        citations = hypothesis.citations.all()
        context = self._get_citations_context()
        serializer = DynamicCitationSerializer(
            citations,
            _include_fields=[
                'id',
                'created_by',
                'source',
                'created_date',
                'updated_date',
            ],
            many=True,
            context=context
        )
        return Response(serializer.data, status=200)

    def _get_citations_context(self):
        context = {
            'usr_dus_get_author_profile': {
                '_include_fields': [
                    'id',
                    'first_name',
                    'last_name',
                    'profile_image',
                ]
            },
            'hyp_dcs_get_created_by': {
                '_include_fields': [
                    'id',
                    'author_profile'
                ]
            },
            'hyp_dcs_get_source': {
                '_include_fields': [
                    'id',
                    'documents',
                    'document_type',
                ]
            },
            'doc_duds_get_documents': {
                '_include_fields': [
                    'id',
                    'title',
                    'paper_title',
                ]
            }
        }
        return context
