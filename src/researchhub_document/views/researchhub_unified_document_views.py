from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import (
    AllowAny, 
    # IsAuthenticated
)

from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.serializers import (
  ResearchhubUnifiedDocumentSerializer
)


class ResearchhubUnifiedDocumentViewSet(ModelViewSet):
    permission_classes = [
        AllowAny,
        # IsAuthenticated,
    ]
    queryset = ResearchhubUnifiedDocument.objects.all().order_by(
      "-created_date"
    )
    serializer_class = ResearchhubUnifiedDocumentSerializer
