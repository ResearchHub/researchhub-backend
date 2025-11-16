from rest_framework import serializers

from .models import List, ListItem


class ListSerializer(serializers.ModelSerializer):
    class Meta:
        model = List
        fields = [
            "id",
            "name",
            "is_public",
            "created_date",
            "updated_date",
            "created_by",
            "updated_by",
        ]
        read_only_fields = ["id", "created_date", "updated_date", "created_by", "updated_by"]

class ListItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListItem
        fields = [
            "id",
            "parent_list",
            "unified_document",
            "created_date",
            "updated_date",
            "created_by",
            "updated_by",
        ]
        read_only_fields = ["id", "created_date", "updated_date", "created_by", "updated_by"]
