from rest_framework.viewsets import ModelViewSet

from paper.models import AsyncPaperUpdator


class AsyncPaperUpdatorViewSet(ModelViewSet):
    queryset = AsyncPaperUpdator.objects.filter()
    # alllo
