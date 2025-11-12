from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers

from feed.models import FeedEntry
from feed.serializers import FeedEntrySerializer, serialize_feed_metrics
from researchhub_document.related_models.researchhub_unified_document_model import ResearchhubUnifiedDocument
from utils.serializers import DefaultAuthenticatedSerializer

from .models import List, ListItem


class ListSerializer(DefaultAuthenticatedSerializer):
    items_count = serializers.SerializerMethodField()

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
            "items_count",
        ]
        read_only_fields = ["id", "created_date", "updated_date", "created_by", "updated_by"]

    def get_items_count(self, obj):
        if hasattr(obj, '_prefetched_objects_cache') and 'items' in obj._prefetched_objects_cache:
            return len([item for item in obj._prefetched_objects_cache['items'] if not item.is_removed])
        return obj.items.filter(is_removed=False).count()


class ListItemSerializer(DefaultAuthenticatedSerializer):
    unified_document = serializers.SerializerMethodField()

    class Meta:
        model = ListItem
        fields = ["id", "parent_list", "unified_document", "created_date", "created_by"]
        read_only_fields = ["id", "created_date", "created_by"]
        extra_kwargs = {
            'unified_document': {'required': True}
        }

    def get_fields(self):
        fields = super().get_fields()
        if self.context.get('request') and self.context['request'].method in ['POST', 'PUT', 'PATCH']:
            fields['unified_document'] = serializers.PrimaryKeyRelatedField(
                queryset=ResearchhubUnifiedDocument.objects.filter(is_removed=False), 
                required=True
            )
        return fields

    def get_unified_document(self, obj):
        feed_entry = obj.unified_document.feed_entries.select_related(
            "content_type", "user", "user__author_profile"
        ).first()
        
        if not feed_entry:
            item = (obj.unified_document.posts.first() if hasattr(obj.unified_document, 'posts') 
                    and obj.unified_document.posts.exists() else 
                    obj.unified_document.paper if hasattr(obj.unified_document, 'paper') else None)
            
            if item:
                content_type = ContentType.objects.get_for_model(item)
                author = getattr(item, 'created_by', None) or getattr(item, 'uploaded_by', None)
                feed_entry = FeedEntry(
                    id=item.id,
                    content_type=content_type,
                    object_id=item.id,
                    action="PUBLISH",
                    action_date=getattr(item, 'paper_publish_date', None) or item.created_date,
                    created_date=item.created_date,
                    user=author,
                    unified_document=item.unified_document,
                    hot_score_v2=getattr(item, 'hot_score_v2', 0),
                )
                feed_entry.item = item
                feed_entry.metrics = serialize_feed_metrics(item, content_type)

        if feed_entry:
            return FeedEntrySerializer(feed_entry, context=self.context).data

        return None


class ListDetailSerializer(ListSerializer):
    items = serializers.SerializerMethodField()

    class Meta(ListSerializer.Meta):
        fields = ListSerializer.Meta.fields + ["items"]

    def get_items(self, obj):
        from feed.views.common import FeedPagination
        paginator = FeedPagination()
        items_queryset = obj.items.filter(is_removed=False).order_by("-created_date")
        paginated_items = list(items_queryset[:paginator.page_size])
        return ListItemSerializer(paginated_items, many=True, context=self.context).data


class OverviewItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    unified_document_id = serializers.IntegerField()


class OverviewListSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    is_public = serializers.BooleanField()
    created_by = serializers.IntegerField()
    items = OverviewItemSerializer(many=True)


class OverviewResponseSerializer(serializers.Serializer):
    lists = OverviewListSerializer(many=True)


class UserListOverviewSerializer(serializers.Serializer):
    lists = serializers.SerializerMethodField()

    def __init__(self, queryset=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queryset = queryset

    def get_lists(self, obj):
        if not self.queryset:
            return []

        lists_data = []
        for list_obj in self.queryset:
            if hasattr(list_obj, '_prefetched_objects_cache') and 'items' in list_obj._prefetched_objects_cache:
                items = [item for item in list_obj._prefetched_objects_cache['items'] if not item.is_removed]
                items.sort(key=lambda x: x.created_date, reverse=True)
            else:
                items = list(list_obj.items.filter(is_removed=False).order_by("-created_date"))

            items_data = [
                {
                    "id": item.id,
                    "unified_document_id": item.unified_document_id,
                }
                for item in items
            ]

            lists_data.append({
                "id": list_obj.id,
                "name": list_obj.name,
                "is_public": list_obj.is_public,
                "items": items_data,
            })

        return lists_data

    def to_representation(self, instance):
        return {"lists": self.get_lists(None)}