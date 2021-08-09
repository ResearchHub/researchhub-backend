from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from discussion.reaction_views import ReactionViewActionMixin
from hub.models import Hub
from hypothesis.models import Hypothesis
from hypothesis.serializers import HypothesisSerializer
from researchhub_document.models import (
    ResearchhubUnifiedDocument
)
from researchhub_document.related_models.constants.document_type import (
    HYPOTHESIS
)


class HypothesisViewSet(ModelViewSet, ReactionViewActionMixin):
    ordering = ('-created_date')
    queryset = Hypothesis.objects
    permission_classes = [AllowAny] #[IsAuthenticated]
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
