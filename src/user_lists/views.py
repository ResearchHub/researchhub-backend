from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response

from feed.views.common import FeedPagination

from .models import List, ListItem
from .serializers import ListDetailSerializer, ListItemDetailSerializer, ListItemSerializer, ListSerializer


class ListAccessPermission(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return obj.can_be_accessed_by(request.user)
        return obj.can_be_modified_by(request.user)


class ListViewSet(viewsets.ModelViewSet):
    queryset = List.objects.filter(is_removed=False)
    serializer_class = ListSerializer
    permission_classes = [ListAccessPermission]
    pagination_class = FeedPagination

    def get_queryset(self):
        if self.action == "list":
            return self.queryset.filter(created_by=self.request.user).order_by("-updated_date")
        return self.queryset.order_by("-updated_date")

    def get_object(self):
        queryset = self.queryset
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        obj = get_object_or_404(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj

    def get_serializer_class(self):
        return ListDetailSerializer if self.action == "retrieve" else ListSerializer

    def perform_create(self, serializer):
        try:
            serializer.save(created_by=self.request.user)
        except IntegrityError:
            raise serializers.ValidationError({"error": "A list with this name already exists."})

    def perform_update(self, serializer):
        try:
            instance = serializer.save(updated_by=self.request.user)
            instance.update_timestamp(self.request.user)
        except IntegrityError:
            raise serializers.ValidationError({"error": "A list with this name already exists."})

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        for item in instance.active_items:
            item.delete()
        return Response({"success": True}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="user_check")
    def user_check(self, request):
        lists_data = [
            {
                "id": list_instance.id,
                "name": list_instance.name,
                "created_by": list_instance.created_by_id,
                "items": [
                    {"id": item.id, "unified_document_id": item.unified_document_id}
                    for item in list_instance.active_items.order_by("-created_date")
                ],
            }
            for list_instance in self.get_queryset().filter(created_by=self.request.user).prefetch_related("items")
        ]
        return Response({"lists": lists_data}, status=status.HTTP_200_OK)


class ListItemAccessPermission(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return obj.parent_list.can_be_accessed_by(request.user)
        return obj.created_by == request.user


class ListItemViewSet(viewsets.ModelViewSet):
    queryset = ListItem.objects.filter(is_removed=False)
    serializer_class = ListItemSerializer
    permission_classes = [ListItemAccessPermission]
    pagination_class = FeedPagination

    def get_queryset(self):
        queryset = self.queryset
        if parent_list_id := self.request.query_params.get("parent_list"):
            queryset = queryset.filter(
                parent_list_id=parent_list_id,
                parent_list__is_removed=False,
            )
        return queryset.order_by("-created_date")

    def get_object(self):
        queryset = self.queryset
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        obj = get_object_or_404(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj

    def get_serializer_class(self):
        return ListItemDetailSerializer if self.action in ["retrieve", "list"] else ListItemSerializer

    def perform_create(self, serializer):
        try:
            item = serializer.save(created_by=self.request.user)
            serializer.validated_data["parent_list"].update_timestamp(self.request.user)
        except IntegrityError:
            raise serializers.ValidationError({"error": "Item already exists in this list."})

    def perform_update(self, serializer):
        previous_parent = serializer.instance.parent_list
        parent_list = serializer.validated_data.get("parent_list", previous_parent)
        try:
            serializer.save(updated_by=self.request.user)
            parent_list.update_timestamp(self.request.user)
            if previous_parent != parent_list:
                previous_parent.update_timestamp(self.request.user)
        except IntegrityError:
            raise serializers.ValidationError({"error": "Item already exists in this list."})

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        parent_list = instance.parent_list
        instance.delete()
        parent_list.update_timestamp(request.user)
        return Response({"success": True}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="add-item-to-list")
    def add_item_to_list(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parent_list = serializer.validated_data["parent_list"]
        unified_document = serializer.validated_data["unified_document"]

        existing_item = ListItem.find_existing(parent_list, unified_document)
        if existing_item:
            return Response(
                {
                    "error": "Item already in list",
                    "item": ListItemDetailSerializer(existing_item, context={"request": request}).data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            self.perform_create(serializer)
            return Response(
                ListItemDetailSerializer(serializer.instance, context={"request": request}).data,
                status=status.HTTP_201_CREATED,
            )
        except serializers.ValidationError as e:
            existing_item = ListItem.find_existing(parent_list, unified_document)
            if existing_item:
                return Response(
                    {
                        "error": "Item already in list",
                        "item": ListItemDetailSerializer(existing_item, context={"request": request}).data,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            raise

    @action(detail=False, methods=["post"], url_path="remove-item-from-list")
    def remove_item_from_list(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        list_item = ListItem.find_existing(
            serializer.validated_data["parent_list"], serializer.validated_data["unified_document"]
        )
        if not list_item or list_item.created_by != request.user:
            return Response({"error": "Item not found in list"}, status=status.HTTP_404_NOT_FOUND)
        parent_list = list_item.parent_list
        list_item.delete()
        parent_list.update_timestamp(request.user)
        return Response({"success": True}, status=status.HTTP_200_OK)
