from django.db import IntegrityError
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.mixins import CreateModelMixin, DestroyModelMixin, ListModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination

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

class ListItemViewSet(CreateModelMixin, ListModelMixin, DestroyModelMixin, viewsets.GenericViewSet):
    queryset = ListItem.objects.filter(is_removed=False)
    serializer_class = ListItemSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = ListPagination
    lookup_field = 'item_id'
    lookup_url_kwarg = 'item_id'

    def get_queryset(self):
        list_id = self.kwargs.get('list_id')
        qs = self.queryset.filter(
            parent_list__created_by=self.request.user
        ).select_related(
            'unified_document'
        ).prefetch_related(
            'unified_document__paper',
            'unified_document__posts'
        )
        
        if list_id:
            qs = qs.filter(parent_list_id=list_id, unified_document__is_removed=False)
        
        return qs

    def list(self, request, *args, **kwargs):
        list_id = kwargs.get('list_id')
        
        check_list_exists = List.objects.filter(id=list_id, created_by=request.user, is_removed=False).exists()
        if not check_list_exists:
            return Response({"error": "List not found"}, status=status.HTTP_404_NOT_FOUND)
        
        return super().list(request, *args, **kwargs)

    def _get_or_create_default_list(self, user):
        default_list, _ = List.objects.get_or_create(
            created_by=user,
            is_default=True,
            defaults={'name': None, 'is_removed': False}
        )
        return default_list

    def create(self, request, *args, **kwargs):
        data = request.data
        # when creating a new item, if no parent list is provided in the POST request (one click add to list instead of selecting a list), get or create the default list
        if not data.get('parent_list'):
            default_list = self._get_or_create_default_list(request.user)
            data = {'unified_document': data.get('unified_document'), 'parent_list': default_list.id}
        
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        try:
            instance = serializer.save(created_by=request.user)
            instance.parent_list.save(update_fields=['updated_date'])
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except IntegrityError:
            return Response({"error": "Document already exists in list"}, status=status.HTTP_400_BAD_REQUEST)

    def perform_destroy(self, instance):
        parent_list = instance.parent_list
        super().perform_destroy(instance)
        parent_list.save(update_fields=['updated_date'])

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        item_id = self.kwargs.get('item_id')
        obj = get_object_or_404(queryset, id=item_id)
        return obj
