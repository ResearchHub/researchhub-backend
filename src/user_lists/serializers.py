from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers

from feed.models import FeedEntry
from feed.serializers import FeedEntrySerializer
from researchhub_comment.related_models.rh_comment_model import RhCommentModel

from .models import List, ListItem


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
        read_only_fields = ["id", "created_date", "updated_date", "created_by", "updated_by"]

class ListOverviewSerializer(serializers.ModelSerializer):
    list_id = serializers.IntegerField(source="id", read_only=True)
    unified_documents = serializers.SerializerMethodField()

    class Meta:
        model = List
        fields = ["list_id", "name", "unified_documents"]

    def get_unified_documents(self, obj):
        return [
            {"list_item_id": item.id, "unified_document_id": item.unified_document_id}
            for item in obj.items.all()
        ]
        
class ListItemSerializer(serializers.ModelSerializer):
    feed_entry = serializers.SerializerMethodField()

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
            "feed_entry",
        ]
        read_only_fields = ["id", "created_date", "updated_date", "created_by", "updated_by", "feed_entry"]
    
    def get_feed_entry(self, obj):
        feed_entry = FeedEntry.objects.filter(
            unified_document_id=obj.unified_document_id
        ).exclude(
            content_type=ContentType.objects.get_for_model(RhCommentModel)
        ).select_related(
            "content_type", "user", "user__author_profile", "user__userverification"
        ).first()
        
        if feed_entry:
            return FeedEntrySerializer(feed_entry, context=self.context).data
        return None
    
    def validate(self, data):
        request = self.context.get("request")
        parent_list = data.get("parent_list")
        
        if parent_list:
            user = getattr(request, "user", None) if request else None
            if not user or parent_list.created_by != user or parent_list.is_removed:
                raise serializers.ValidationError("Invalid list")  
        return data
