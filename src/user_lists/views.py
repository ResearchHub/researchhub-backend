from rest_framework import viewsets
from rest_framework.mixins import CreateModelMixin
from rest_framework.permissions import IsAuthenticated

from .models import List
from .serializers import ListSerializer


class ListViewSet(CreateModelMixin, viewsets.GenericViewSet):
    queryset = List.objects.filter(is_removed=False)
    serializer_class = ListSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

