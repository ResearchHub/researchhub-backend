from django.db import IntegrityError
from django.db.models import Count, Prefetch, Q
from rest_framework import status, viewsets
from rest_framework.mixins import DestroyModelMixin, ListModelMixin
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action
from feed.views.common import FeedPagination

from .models import List, ListItem
from .serializers import ListOverviewSerializer, ListSerializer, ListItemSerializer


class ListPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class ListViewSet(viewsets.ModelViewSet):
    queryset = List.objects.filter(is_removed=False)
    serializer_class = ListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = ListPagination

    def get_queryset(self):
        return self.queryset.filter(created_by=self.request.user).annotate(
            item_count=Count("items", filter=Q(items__is_removed=False))
        ).order_by("-updated_date")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    @action(detail=False, methods=["get"])
    def overview(self, request):
        lists = self.get_queryset().prefetch_related(
            Prefetch("items", queryset=ListItem.objects.filter(is_removed=False))
        )

        serializer = ListOverviewSerializer(lists, many=True, context=self.get_serializer_context())
        return Response({"lists": serializer.data}, status=status.HTTP_200_OK)

class ListItemViewSet(ListModelMixin, DestroyModelMixin, viewsets.GenericViewSet):
    queryset = ListItem.objects.filter(is_removed=False)
    serializer_class = ListItemSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = FeedPagination

    def get_queryset(self):
        qs = self.queryset.filter(parent_list__created_by=self.request.user)
        parent_list_id = self.request.query_params.get("parent_list")
        if parent_list_id:
            qs = qs.filter(parent_list_id=parent_list_id, unified_document__is_removed=False)
        
        return qs

    def list(self, request, *args, **kwargs):
        parent_list_id = request.query_params.get("parent_list")
        if not parent_list_id:
            return Response({"error": "parent_list is required"}, status=status.HTTP_400_BAD_REQUEST)
        check_list_exists = List.objects.filter(id=parent_list_id, created_by=request.user, is_removed=False).exists()
        if not check_list_exists:
            return Response({"error": "List not found"}, status=status.HTTP_404_NOT_FOUND)
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(created_by=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except IntegrityError:
            return Response({"error": "Document already exists in list"}, status=status.HTTP_400_BAD_REQUEST)
