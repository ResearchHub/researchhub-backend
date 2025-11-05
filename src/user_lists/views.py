from django.db import IntegrityError
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from feed.views.common import FeedPagination
from researchhub.permissions import IsObjectOwner

from .models import List, ListItem
from .serializers import ListDetailSerializer, ListItemDetailSerializer, ListItemSerializer, ListSerializer


def _update_list_timestamp(list_obj, user):
    list_obj.updated_date = timezone.now()
    list_obj.updated_by = user
    list_obj.save(update_fields=["updated_date", "updated_by"])


def _handle_integrity_error_list_name():
    raise serializers.ValidationError({"error": "A list with this name already exists."})


def _handle_integrity_error_item():
    raise serializers.ValidationError({"error": "Item already exists in this list."})


class ListViewSet(viewsets.ModelViewSet):
    queryset = List.objects.filter(is_removed=False)
    serializer_class = ListSerializer
    permission_classes = [IsAuthenticated, IsObjectOwner]
    pagination_class = FeedPagination

    def get_queryset(self):
        return self.queryset.filter(created_by=self.request.user).order_by("-updated_date")

    def get_serializer_class(self):
        return ListDetailSerializer if self.action == "retrieve" else ListSerializer

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

    @action(detail=False, methods=["get"], url_path="user_check")
    def user_check(self, request):
        """
        Lightweight endpoint to get user's lists with item IDs for quick frontend checks.
        Returns lists with their item IDs and unified_document IDs so the frontend can:
        - Know what lists the user has
        - Check if an item already exists in a list
        - Get the ListItem ID needed to remove an item
        """
        user_lists = self.get_queryset().prefetch_related("items")
        
        lists_data = []
        for list_obj in user_lists:
            items = list_obj.items.filter(is_removed=False).order_by("-created_date")
            items_data = [
                {
                    "id": item.id,  # ListItem ID for removal
                    "unified_document_id": item.unified_document_id,  # For checking if doc exists in list
                }
                for item in items
            ]
            
            lists_data.append({
                "id": list_obj.id,
                "name": list_obj.name,
                "is_public": list_obj.is_public,
                "items": items_data,
            })
        
        return Response({"lists": lists_data}, status=status.HTTP_200_OK)


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

    def _serialize_item(self, item):
        try:
            return ListItemDetailSerializer(item, context={"request": self.request}).data
        except Exception:
            return {"id": item.id}

    def _existing_item_response(self, existing_item):
        return Response(
            {"error": "Item already in list", "item": self._serialize_item(existing_item)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    @action(detail=False, methods=["post"], url_path="add-item-to-list")
    def add_item_to_list(self, request):
        serializer = ListItemSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        parent_list = serializer.validated_data["parent_list"]
        unified_document = serializer.validated_data["unified_document"]

        self._validate_parent_list(parent_list)

        existing_item = self._find_existing_item(parent_list, unified_document)
        if existing_item:
            return self._existing_item_response(existing_item)

        try:
            list_item, _ = self._get_or_create_item(serializer, request.user)
            return Response(self._serialize_item(list_item), status=status.HTTP_201_CREATED)
        except IntegrityError:
            existing_item = self._find_existing_item(parent_list, unified_document)
            if existing_item:
                return self._existing_item_response(existing_item)
            _handle_integrity_error_item()

    @action(detail=False, methods=["post"], url_path="remove-item-from-list")
    def remove_item_from_list(self, request):
        serializer = ListItemSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        list_item = self._find_existing_item(
            serializer.validated_data["parent_list"], serializer.validated_data["unified_document"]
        )
        if not list_item or list_item.created_by != request.user:
            return Response({"error": "Item not found in list"}, status=status.HTTP_404_NOT_FOUND)
        parent_list = list_item.parent_list
        list_item.delete()
        _update_list_timestamp(parent_list, request.user)
        return Response({"success": True}, status=status.HTTP_200_OK)
