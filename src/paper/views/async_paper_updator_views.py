from rest_framework.viewsets import ModelViewSet

from paper.models import AsyncPaperUpdator
from paper.permissions import IsAllowedToUpdateAsyncPaper
from paper.serializers.async_paper_updator_serializer import AsyncPaperUpdatorSerializer


class AsyncPaperUpdatorViewSet(ModelViewSet):
    http_method_names = ["post"]
    permission_classes = [IsAllowedToUpdateAsyncPaper]
    queryset = AsyncPaperUpdator.objects.filter()
    serializer_class = AsyncPaperUpdatorSerializer
