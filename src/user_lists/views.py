from django.db import IntegrityError
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.mixins import DestroyModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import List, ListItem
from .serializers import ListSerializer, ListItemSerializer


class ListViewSet(viewsets.ModelViewSet):
    queryset = List.objects.filter(is_removed=False)
    serializer_class = ListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(created_by=self.request.user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    def perform_destroy(self, instance):
        instance.delete()


class ListItemViewSet(DestroyModelMixin, viewsets.GenericViewSet):
    queryset = ListItem.objects.filter(is_removed=False)
    serializer_class = ListItemSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(parent_list__created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        parent_list = serializer.validated_data.get('parent_list')
        if parent_list.created_by != request.user or parent_list.is_removed:
            raise NotFound()
        
        try:
            serializer.save(created_by=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except IntegrityError:
            return Response(
                {"error": "Document already exists in list"},
                status=status.HTTP_400_BAD_REQUEST
            )

    def perform_destroy(self, instance):
        instance.delete()
