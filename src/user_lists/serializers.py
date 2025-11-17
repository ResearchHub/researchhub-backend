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
    
    def validate(self, data):
        request = self.context.get("request")
        parent_list = data.get("parent_list")
        
        if parent_list:
            user = getattr(request, "user", None) if request else None
            if not user or parent_list.created_by != user or parent_list.is_removed:
                raise serializers.ValidationError("Invalid list")  
        return data
