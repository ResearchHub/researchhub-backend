from django.utils import timezone
from rest_framework.serializers import ValidationError
from django.db import IntegrityError

from .models import ListItem
from .serializers import ListItemDetailSerializer


class ListTimestampMixin:
    def _update_list_timestamp(self, list_obj, user):
        list_obj.updated_date = timezone.now()
        list_obj.updated_by = user
        list_obj.save(update_fields=["updated_date", "updated_by"])


class ListItemMixin:
    def _handle_integrity_error_item(self):
        raise ValidationError({"error": "Item already exists in this list."})

    def _validate_parent_list(self, parent_list):
        if parent_list.created_by != self.request.user or parent_list.is_removed:
            raise ValidationError({"parent_list": "List not found or you don't have permission."})

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
        from rest_framework.response import Response
        from rest_framework import status
        
        return Response(
            {"error": "Item already in list", "item": self._serialize_item(existing_item)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def _get_or_create_item(self, serializer, created_by):
        parent_list = serializer.validated_data.get("parent_list")
        self._validate_parent_list(parent_list)
        try:
            item = serializer.save(created_by=created_by)
            self._update_list_timestamp(parent_list, created_by)
            return item, parent_list
        except IntegrityError:
            self._handle_integrity_error_item()

