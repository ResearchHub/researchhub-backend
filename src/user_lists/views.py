from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from feed.views.common import FeedPagination
from researchhub.permissions import IsObjectOwner
from django.db import IntegrityError

from .models import List, ListItem
from .serializers import (
    ListDetailSerializer,
    ListItemDetailSerializer,
    ListItemSerializer,
    ListSerializer,
    ToggleListItemResponseSerializer,
    UserListOverviewSerializer,
)


def _update_list_timestamp(list_obj, user):
    list_obj.updated_date = timezone.now()
    list_obj.updated_by = user
    list_obj.save(update_fields=["updated_date", "updated_by"])

def _handle_integrity_error_item():
    raise serializers.ValidationError({"error": "Item already exists in this list."})

class ListViewSet(viewsets.ModelViewSet):
    queryset = List.objects.filter(is_removed=False)
    serializer_class = ListSerializer
    permission_classes = [IsAuthenticated, IsObjectOwner]
    pagination_class = FeedPagination

    def get_queryset(self):
        return self.queryset.filter(created_by=self.request.user).prefetch_related("items").order_by("-updated_date")

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

    def perform_update(self, serializer):
        instance = serializer.save(updated_by=self.request.user)
        _update_list_timestamp(instance, self.request.user)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        instance.items.filter(is_removed=False).delete()
        return Response({"success": True}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="overview")
    def overview(self, request):
        user_lists = self.queryset.filter(created_by=request.user).prefetch_related("items").order_by("-updated_date")
        serializer = UserListOverviewSerializer(queryset=user_lists)
        return Response(serializer.to_representation(None), status=status.HTTP_200_OK)


class ListItemViewSet(viewsets.ModelViewSet):
    queryset = ListItem.objects.filter(is_removed=False)
    serializer_class = ListItemSerializer
    permission_classes = [IsAuthenticated, IsObjectOwner]
    pagination_class = FeedPagination

    def get_queryset(self):
        queryset = self.queryset.filter(created_by=self.request.user).order_by("-created_date")
        parent_list_id = self.request.query_params.get("parent_list")
        if parent_list_id:
            queryset = queryset.filter(
                parent_list_id=parent_list_id,
                parent_list__created_by=self.request.user,
                parent_list__is_removed=False,
            )
        return queryset

    def get_serializer_class(self):
        return ListItemDetailSerializer if self.action in ["retrieve", "list"] else ListItemSerializer

    def _validate_parent_list(self, parent_list):
        if parent_list.created_by != self.request.user or parent_list.is_removed:
            raise serializers.ValidationError({"parent_list": "List not found or you don't have permission."})

    def _get_or_create_item(self, serializer, created_by):
        parent_list = serializer.validated_data.get("parent_list")
        self._validate_parent_list(parent_list)
        try:
            item = serializer.save(created_by=created_by)
            _update_list_timestamp(parent_list, created_by)
            return item, parent_list
        except IntegrityError:
            _handle_integrity_error_item()

    def perform_create(self, serializer):
        self._get_or_create_item(serializer, self.request.user)

    def perform_update(self, serializer):
        parent_list = serializer.validated_data.get("parent_list", serializer.instance.parent_list)
        self._validate_parent_list(parent_list)
        try:
            serializer.save(updated_by=self.request.user)
            _update_list_timestamp(parent_list, self.request.user)
        except IntegrityError:
            _handle_integrity_error_item()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        parent_list = instance.parent_list
        instance.delete()
        _update_list_timestamp(parent_list, request.user)
        return Response({"success": True}, status=status.HTTP_200_OK)

    def _find_existing_item(self, parent_list, unified_document):
        return ListItem.objects.filter(
            parent_list=parent_list, unified_document=unified_document, is_removed=False
        ).first()

    @action(detail=False, methods=["post"], url_path="add-item-to-list")
    def add_item_to_list(self, request):
        serializer = ListItemSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        parent_list = serializer.validated_data["parent_list"]
        unified_document = serializer.validated_data["unified_document"]
        self._validate_parent_list(parent_list)

        existing_item = self._find_existing_item(parent_list, unified_document)
        if existing_item:
            raise serializers.ValidationError({"error": "Item already exists in this list."})

        try:
            list_item, _ = self._get_or_create_item(serializer, request.user)
            response_data = {
                "action": "added",
                "item": list_item,
                "success": True,
            }
            response_serializer = ToggleListItemResponseSerializer(
                response_data
            )
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        except IntegrityError:
            _handle_integrity_error_item()

    @action(detail=False, methods=["post"], url_path="remove-item-from-list")
    def remove_item_from_list(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parent_list = serializer.validated_data["parent_list"]
        unified_document = serializer.validated_data["unified_document"]
        self._validate_parent_list(parent_list)

        list_item = self._find_existing_item(parent_list, unified_document)
        if not list_item or list_item.created_by != request.user:
            return Response({"error": "Item not found in list"}, status=status.HTTP_404_NOT_FOUND)
        
        parent_list = list_item.parent_list
        list_item.delete()
        _update_list_timestamp(parent_list, request.user)
        
        response_data = {
            "action": "removed",
            "item": None,
            "success": True,
        }
        response_serializer = ToggleListItemResponseSerializer(
            response_data
        )
        return Response(response_serializer.data, status=status.HTTP_200_OK)
