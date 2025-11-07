from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.mixins import CreateModelMixin, DestroyModelMixin, UpdateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from researchhub.permissions import IsObjectOwner

from .models import List
from .serializers import ListSerializer


def _update_list_timestamp(list_obj, user):
    list_obj.updated_date = timezone.now()
    list_obj.updated_by = user
    list_obj.save(update_fields=["updated_date", "updated_by"])


class ListViewSet(CreateModelMixin, UpdateModelMixin, DestroyModelMixin, viewsets.GenericViewSet):
    queryset = List.objects.filter(is_removed=False)
    serializer_class = ListSerializer
    permission_classes = [IsAuthenticated, IsObjectOwner]

    def get_queryset(self):
        return self.queryset.filter(created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            # Format validation errors into a single error message
            error_messages = []
            for field, errors in serializer.errors.items():
                if isinstance(errors, list):
                    error_messages.extend([f"{field}: {error}" for error in errors])
                else:
                    error_messages.append(f"{field}: {errors}")
            error_message = " ".join(error_messages) if error_messages else "Validation error"
            return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)
        
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        instance = serializer.save(updated_by=self.request.user)
        _update_list_timestamp(instance, self.request.user)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        instance.items.filter(is_removed=False).delete()
        return Response({"success": True}, status=status.HTTP_200_OK)

