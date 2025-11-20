from django.db import IntegrityError
from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.mixins import DestroyModelMixin, ListModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from feed.views.common import FeedPagination

from .models import List, ListItem
from .serializers import ListSerializer, ListItemSerializer


class ListViewSet(viewsets.ModelViewSet):
    queryset = List.objects.filter(is_removed=False)
    serializer_class = ListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = PageNumberPagination

    def get_queryset(self):
        return self.queryset.filter(created_by=self.request.user).annotate(
            item_count=Count("items", filter=Q(items__is_removed=False))
        ).order_by("-updated_date")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class ListItemViewSet(ListModelMixin, DestroyModelMixin, viewsets.GenericViewSet):
    queryset = ListItem.objects.filter(is_removed=False)
    serializer_class = ListItemSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = FeedPagination

    def get_queryset(self):
        qs = self.queryset.filter(
            parent_list__created_by=self.request.user
        ).select_related(
            'unified_document'
        ).prefetch_related(
            'unified_document__paper',
            'unified_document__posts'
        )
        
        if self.action == 'retrieve':
            list_id = self.kwargs.get('pk')
            if list_id:
                qs = qs.filter(parent_list_id=list_id, unified_document__is_removed=False)
        
        return qs

    def retrieve(self, request, *args, **kwargs):
        list_id = kwargs.get('pk')
        
        check_list_exists = List.objects.filter(id=list_id, created_by=request.user, is_removed=False).exists()
        if not check_list_exists:
            return Response({"error": "List not found"}, status=status.HTTP_404_NOT_FOUND)
        
        return self.list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(created_by=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except IntegrityError:
            return Response({"error": "Document already exists in list"}, status=status.HTTP_400_BAD_REQUEST)
