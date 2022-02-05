from researchhub_document.utils import reset_unified_document_cache
from django.core.files.base import ContentFile
from rest_framework.permissions import (
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
from researchhub_document.permissions import HasDocumentEditingPermission


class HypothesisViewSet(ModelViewSet, ReactionViewActionMixin):
    ordering = ('-created_date')
    queryset = Hypothesis.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly, HasDocumentEditingPermission]
    serializer_class = HypothesisSerializer

    def create(self, request, *args, **kwargs):
        user = request.user
        data = request.data
        renderable_text = data.get('renderable_text', '')
        src = data.get('full_src', '')
        title = data.get('title', '')
        unified_doc = self._create_unified_doc(request)
        file_name, file = self._create_src_content_file(unified_doc, src, user)

        hypo = Hypothesis.objects.create(
            created_by=user,
            title=title,
            renderable_text=renderable_text,
            unified_document=unified_doc
        )
        hypo.src.save(file_name, file)
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

    @action(detail=True, methods=['post'])
    def upsert(self, request, *args, **kwargs):
        user = request.user
        hypo = Hypothesis.objects.get(id=request.data.get('hypothesis_id'))
        unified_doc = hypo.unified_document
        serializer = HypothesisSerializer(
            hypo,
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        file_name, full_src_file = self._create_src_content_file(
            unified_doc, request.data['full_src'], user
        )
        serializer.instance.src.save(file_name, full_src_file)

        reset_unified_document_cache([0])
        return Response(request.data, status=200)

    def _create_src_content_file(self, unified_doc, data, user):
        file_name = f'HYPOTHESIS-{unified_doc.id}--USER-{user.id}.txt'
        full_src_file = ContentFile(data.encode())
        return file_name, full_src_file

    @action(detail=True, methods=['get'])
    def get_citations(self, request, pk=None):
        citation_type = request.GET.get('citation_type')
        hypothesis = self.get_object()
        citations = hypothesis.citations.all().order_by('-vote_score')

        citation_set = citations.filter(
            citation_type=citation_type
        ) if citation_type else citations

        context = self._get_citations_context()
        context['request'] = request
        
        serializer = DynamicCitationSerializer(
            citation_set,
            _include_fields=[
                'citation_type',
                'consensus_meta',
                'created_by',
                'created_date',
                'id',
                'publish_date',
                'score',
                'source',
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
                    'doi',
                ]
            },
            'doc_duds_get_documents': {
                '_include_fields': [
                    'created_date',
                    'doi',
                    'id',
                    'paper_title',
                    'slug',
                    'title',
                ]
            }
        }
        return context
