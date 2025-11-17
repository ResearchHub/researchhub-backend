from django.db import IntegrityError
from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.mixins import DestroyModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.serializers import ResearchhubUnifiedDocumentSerializer

from .models import List, ListItem
from .serializers import ListSerializer, ListItemSerializer


class ListViewSet(viewsets.ModelViewSet):
    queryset = List.objects.filter(is_removed=False)
    serializer_class = ListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(created_by=self.request.user).annotate(
            item_count=Count("items", filter=Q(items__is_removed=False))
        ).order_by("-updated_date")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class ListItemViewSet(DestroyModelMixin, viewsets.GenericViewSet):
    queryset = ListItem.objects.filter(is_removed=False)
    serializer_class = ListItemSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(parent_list__created_by=self.request.user)

    def list(self, request, *args, **kwargs):
        parent_list = request.query_params.get("parent_list")
        if not parent_list:
            return Response({"error": "parent_list is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        items = self.get_queryset().filter(parent_list_id=parent_list).values_list("unified_document_id", flat=True)
        unified_docs = ResearchhubUnifiedDocument.objects.filter(id__in=items, is_removed=False)
        
        page = self.paginate_queryset(unified_docs)
        if page is not None:
            serializer = ResearchhubUnifiedDocumentSerializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)
        
        serializer = ResearchhubUnifiedDocumentSerializer(unified_docs, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(created_by=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except IntegrityError:
            return Response({"error": "Document already exists in list"}, status=status.HTTP_400_BAD_REQUEST)
