from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.mixins import CreateModelMixin, DestroyModelMixin, UpdateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.serializers import ValidationError

from researchhub.permissions import IsObjectOwner

from .models import List
from .serializers import ListSerializer


def _update_list_timestamp(list_obj, user):
    list_obj.updated_date = timezone.now()
    list_obj.updated_by = user
    list_obj.save(update_fields=["updated_date", "updated_by"])


def _handle_integrity_error_list_name():
    raise ValidationError({"name": "A list with this name already exists."})


class ListViewSet(CreateModelMixin, UpdateModelMixin, DestroyModelMixin, viewsets.GenericViewSet):
    queryset = List.objects.filter(is_removed=False)
    serializer_class = ListSerializer
    permission_classes = [IsAuthenticated, IsObjectOwner]

    def get_queryset(self):
        return self.queryset.filter(created_by=self.request.user)

    def perform_create(self, serializer):
        try:
            serializer.save(created_by=self.request.user)
        except IntegrityError:
            _handle_integrity_error_list_name()

    def perform_update(self, serializer):
        try:
            instance = serializer.save(updated_by=self.request.user)
            _update_list_timestamp(instance, self.request.user)
        except IntegrityError:
            _handle_integrity_error_list_name()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        instance.items.filter(is_removed=False).delete()
        return Response({"success": True}, status=status.HTTP_200_OK)

