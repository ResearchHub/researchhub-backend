from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response
from feed.views.common import FeedPagination 
from .models import List, ListItem
from .serializers import (
    ListDetailSerializer,
    ListItemDetailSerializer,
    ListItemSerializer,
    ListSerializer,
    ToggleListItemResponseSerializer,
    UserListOverviewSerializer,
)


def _handle_integrity_error_item():
    raise serializers.ValidationError({"error": "Item already exists in this list."})

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
        queryset = self.queryset.prefetch_related("items")
        if self.action == "list":
            return queryset.filter(created_by=self.request.user).order_by("-updated_date")
        return queryset.order_by("-updated_date")

    def get_serializer_class(self):
        return ListDetailSerializer if self.action == "retrieve" else ListSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            error_messages = []
            for field, errors in serializer.errors.items():
                if isinstance(errors, list):
                    error_messages.extend([f"{field}: {error}" for error in errors])
                else:
                    error_messages.append(f"{field}: {errors}")
            error_message = " ".join(error_messages) if error_messages else "Validation error"
            return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)
        
        serializer.save(created_by=self.request.user)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if not serializer.is_valid():
            error_messages = []
            for field, errors in serializer.errors.items():
                if isinstance(errors, list):
                    error_messages.extend([f"{field}: {error}" for error in errors])
                else:
                    error_messages.append(f"{field}: {errors}")
            error_message = " ".join(error_messages) if error_messages else "Validation error"
            return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)
        
        self.perform_update(serializer)
        return Response(serializer.data)

    def perform_update(self, serializer):
        instance = serializer.save(updated_by=self.request.user)
        instance.update_timestamp(self.request.user)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        for item in instance.active_items:
            item.delete()
        return Response({"success": True}, status=status.HTTP_200_OK)
    @action(detail=False, methods=["get"], url_path="overview")
    def overview(self, request):
        user_lists = self.get_queryset().prefetch_related("items")
        serializer = UserListOverviewSerializer(queryset=user_lists)
        return Response(serializer.to_representation(None), status=status.HTTP_200_OK)
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

    def _validate_parent_list(self, parent_list):
        if not parent_list.can_be_modified_by(self.request.user):
            raise serializers.ValidationError({"parent_list": "List not found or you don't have permission."})

    def _get_or_create_item(self, serializer, created_by):
        parent_list = serializer.validated_data.get("parent_list")
        self._validate_parent_list(parent_list)
        try:
            item = serializer.save(created_by=created_by)
            parent_list.update_timestamp(created_by)
            return item, parent_list
        except IntegrityError:
            _handle_integrity_error_item()

    def _find_existing_item(self, parent_list, unified_document):
        return ListItem.objects.filter(
            parent_list=parent_list, unified_document=unified_document, is_removed=False
        ).first()

    @action(detail=False, methods=["post"], url_path="toggle-item-in-list")
    def toggle_item_in_list(self, request):
        serializer = ListItemSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        parent_list = serializer.validated_data["parent_list"]
        unified_document = serializer.validated_data["unified_document"]
        self._validate_parent_list(parent_list)

        existing_item = self._find_existing_item(parent_list, unified_document)
        
        if existing_item:
            parent_list = existing_item.parent_list
            existing_item.delete()
            parent_list.update_timestamp(request.user)
            
            response_data = {
                "action": "removed",
                "item": None,
                "success": True,
            }
            response_serializer = ToggleListItemResponseSerializer(
                response_data, context={"request": request}
            )
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        try:
            list_item, _ = self._get_or_create_item(serializer, request.user)
            response_data = {
                "action": "added",
                "item": list_item,
                "success": True,
            }
            response_serializer = ToggleListItemResponseSerializer(
                response_data, context={"request": request}
            )
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        except IntegrityError:
            existing_item = self._find_existing_item(parent_list, unified_document)
            if existing_item:
                parent_list = existing_item.parent_list
                existing_item.delete()
                parent_list.update_timestamp(request.user)
                response_data = {
                    "action": "removed",
                    "item": None,
                    "success": True,
                }
                response_serializer = ToggleListItemResponseSerializer(
                    response_data, context={"request": request}
                )
                return Response(response_serializer.data, status=status.HTTP_200_OK)
            _handle_integrity_error_item()

    @action(detail=False, methods=["post"], url_path="remove-item-from-list")
    def remove_item_from_list(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        list_item = self._find_existing_item(
            serializer.validated_data["parent_list"], serializer.validated_data["unified_document"]
        )
        if not list_item or list_item.created_by != request.user:
            return Response({"error": "Item not found in list"}, status=status.HTTP_404_NOT_FOUND)
        parent_list = list_item.parent_list
        list_item.delete()
        parent_list.update_timestamp(request.user)
        return Response({"success": True}, status=status.HTTP_200_OK)
