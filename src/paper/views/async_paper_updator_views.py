from rest_framework.viewsets import ModelViewSet

from paper.models import AsyncPaperUpdator
from paper.permissions import IsAllowedToUpdateAsyncPaper


class AsyncPaperUpdatorViewSet(ModelViewSet):
    http_method_names = ["post"]
    permission_classes = IsAllowedToUpdateAsyncPaper
    queryset = AsyncPaperUpdator.objects.filter()

    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)
