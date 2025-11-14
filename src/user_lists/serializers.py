from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers

from feed.models import FeedEntry
from feed.serializers import FeedEntrySerializer, serialize_feed_metrics

from .models import List, ListItem


 
READ_ONLY_FIELDS = ["id", "created_date", "updated_date", "created_by", "updated_by"]
COMMON_FIELDS = READ_ONLY_FIELDS + ["is_public"]
LIST_BASE_FIELDS = COMMON_FIELDS + ["name"]
LIST_ITEM_FIELDS = COMMON_FIELDS + ["parent_list", "unified_document"]


class ListSerializer(serializers.ModelSerializer):
    items_count = serializers.SerializerMethodField()

    class Meta:
        model = List
        fields = LIST_BASE_FIELDS + ["items_count"]
        read_only_fields = READ_ONLY_FIELDS

    def get_items_count(self, obj):
        return getattr(obj, "items_count", 0)


class ListItemReadSerializer(serializers.ModelSerializer):
    unified_document = serializers.SerializerMethodField(method_name="get_feed_entry")

    class Meta:
        model = ListItem
        fields = LIST_ITEM_FIELDS
        read_only_fields = LIST_ITEM_FIELDS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._metrics_cache = {}

    def get_feed_entry(self, obj):
        entry = self._get_or_create_feed_entry(obj)
        return FeedEntrySerializer(entry, context=self.context).data if entry else None

    def _get_or_create_feed_entry(self, obj):
        cached = getattr(obj.unified_document, "cached_feed_entries", None)
        if cached is not None and len(cached) > 0:
            return cached[0]
        
        content = self._get_content(obj.unified_document)
        if not content:
            return None

        return self._create_feed_entry(content, obj.unified_document)

    def _get_content(self, document):
        if hasattr(document, "_prefetched_objects_cache") and "posts" in document._prefetched_objects_cache:
            posts = document._prefetched_objects_cache["posts"]
            if posts:
                return posts[0]
        
        try:
            return document.paper
        except (ObjectDoesNotExist, AttributeError):
            return None

    def _create_feed_entry(self, content, document):
        if not content or not hasattr(content, 'id'):
            return None
            
        content_type_cache = self.context.get('content_type_cache', {})
        content_class = content.__class__
        content_type = content_type_cache.get(content_class)
        
        if not content_type:
            return None
        
        metrics_key = (content_class, content.id)
        if metrics_key not in self._metrics_cache:
            self._metrics_cache[metrics_key] = serialize_feed_metrics(content, content_type)

        entry = FeedEntry(
            id=content.id,
            content_type=content_type,
            object_id=content.id,
            action="PUBLISH",
            action_date=getattr(content, "paper_publish_date", None) or getattr(content, "created_date", None),
            created_date=getattr(content, "created_date", None),
            user=getattr(content, "created_by", None) or getattr(content, "uploaded_by", None),
            unified_document=document,
            hot_score_v2=getattr(content, "hot_score_v2", 0),
        )
        entry.item = content
        entry.metrics = self._metrics_cache[metrics_key]
        return entry


class ListItemWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListItem
        fields = LIST_ITEM_FIELDS
        read_only_fields = READ_ONLY_FIELDS

    def validate_parent_list(self, value):
        user = self.context["request"].user
        if value.created_by != user or value.is_removed:
            raise serializers.ValidationError("List not found or you don't have permission.")
        return value

    def validate(self, attrs):
        if self.instance:
            parent_list = attrs.get("parent_list", self.instance.parent_list)
            unified_document = attrs.get("unified_document", self.instance.unified_document)
            
            if parent_list != self.instance.parent_list or unified_document != self.instance.unified_document:
                self._validate_no_duplicate_item(parent_list, unified_document)
        return attrs

    def _validate_no_duplicate_item(self, parent_list, unified_document):
        if ListItem.objects.filter(
            parent_list=parent_list,
            unified_document=unified_document,
            is_removed=False
        ).exclude(id=self.instance.id if self.instance else None).exists():
            raise serializers.ValidationError("Item already exists in this list.")


class OverviewSerializer(ListSerializer):
    items = serializers.SerializerMethodField()

    class Meta:
        model = List
        fields = LIST_BASE_FIELDS + ["items"]
        read_only_fields = READ_ONLY_FIELDS

    def get_items(self, obj):
        limit = self.context.get("items_limit")
        items = getattr(obj, "overview_items", [])
        return [{"id": item.id, "unified_document_id": item.unified_document_id} for item in items[:limit]]
