from django.db import IntegrityError
from rest_framework import viewsets
from rest_framework.mixins import CreateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.serializers import ValidationError

from .models import List
from .serializers import ListSerializer


def _handle_integrity_error_list_name():
    raise ValidationError({"name": "A list with this name already exists."})


class ListViewSet(CreateModelMixin, viewsets.GenericViewSet):
    queryset = List.objects.filter(is_removed=False)
    serializer_class = ListSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        try:
            serializer.save(created_by=self.request.user)
        except IntegrityError:
            _handle_integrity_error_list_name()

