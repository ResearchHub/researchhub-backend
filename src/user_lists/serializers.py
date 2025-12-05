from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers

from feed.serializers import PaperSerializer, PostSerializer, SimpleAuthorSerializer
from researchhub_document.related_models.constants.document_type import (
    PAPER,
    RESEARCHHUB_POST_DOCUMENT_TYPES,
)

from .models import List, ListItem


class ListItemUnifiedDocumentSerializer(serializers.Serializer):
    content_type = serializers.SerializerMethodField()
    content_object = serializers.SerializerMethodField()
    created_date = serializers.DateTimeField()
    author = serializers.SerializerMethodField()
    metrics = serializers.SerializerMethodField()
    
    def get_content_type(self, obj):
            document = obj.get_document()
            if not document:
                return obj.document_type
            return ContentType.objects.get_for_model(type(document)).model.upper()
    
    def get_content_object(self, obj):
            document = obj.get_document()
            if not document:
                return None
            
            if obj.document_type == PAPER:
                return PaperSerializer(document).data
            elif obj.document_type in RESEARCHHUB_POST_DOCUMENT_TYPES:
                return PostSerializer(document).data
            
            return None
    
    def get_author(self, obj):
        if obj.created_by and hasattr(obj.created_by, "author_profile"):
            return SimpleAuthorSerializer(obj.created_by.author_profile).data
        return None
    
    def get_metrics(self, obj):
            document = obj.get_document()
            metrics = {}
            if not document:
                return metrics
            
            if hasattr(document, "score"):
                metrics["votes"] = document.score
            
            if hasattr(document, "get_discussion_count"):
                metrics["comments"] = document.get_discussion_count()
            
            return metrics


class ListSerializer(serializers.ModelSerializer):
    item_count = serializers.IntegerField(read_only=True, required=False)

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
            "item_count",
        ]
        read_only_fields = ["id", "created_date", "updated_date", "created_by", "updated_by", "is_default"]

class ListOverviewSerializer(serializers.ModelSerializer):
    list_id = serializers.IntegerField(source="id", read_only=True)
    unified_documents = serializers.SerializerMethodField()

    class Meta:
        model = List
        fields = ["list_id", "name", "unified_documents", "is_default"]

    def get_unified_documents(self, obj):
        return [
            {"list_item_id": item.id, "unified_document_id": item.unified_document_id}
            for item in obj.items.all()
        ]
        
class ListItemSerializer(serializers.ModelSerializer):
    document = serializers.SerializerMethodField()

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
            "document",
        ]
        read_only_fields = ["id", "created_date", "updated_date", "created_by", "updated_by", "document"]
    
    def get_document(self, obj):
        if obj.unified_document:
            return ListItemUnifiedDocumentSerializer(obj.unified_document, context=self.context).data
        return None
    
    def validate(self, data):
        request = self.context.get("request")
        parent_list = data.get("parent_list")
        
        if parent_list:
            user = getattr(request, "user", None) if request else None
            if not user or parent_list.created_by != user or parent_list.is_removed:
                raise serializers.ValidationError("Invalid list")  
        return data
