from researchhub_document.related_models.researchhub_unified_document_model import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    PAPER,
    RESEARCHHUB_POST_DOCUMENT_TYPES,
)
from researchhub_document.serializers import (
    ResearchhubPostSerializer,
)
from paper.serializers import PaperSerializer
from purchase.serializers import FundraiseSerializer, GrantSerializer
from rest_framework import serializers
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
    unified_document = serializers.PrimaryKeyRelatedField(
        queryset=ResearchhubUnifiedDocument.objects.filter(is_removed=False), required=True
    )

    class Meta:
        model = ListItem
        fields = ["id", "parent_list", "unified_document", "created_date", "created_by"]
        read_only_fields = ["id", "created_date", "created_by"]


class UnifiedDocumentForListSerializer(serializers.ModelSerializer):
    hubs = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()
    fundraise = serializers.SerializerMethodField()
    grant = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    slug = serializers.SerializerMethodField()

    class Meta:
        model = ResearchhubUnifiedDocument
        fields = [
            "id",
            "created_date",
            "title",
            "slug",
            "is_removed",
            "document_type",
            "hubs",
            "created_by",
            "documents",
            "score",
            "hot_score",
            "reviews",
            "fundraise",
            "grant",
        ]
        read_only_fields = fields

    def get_hubs(self, unified_doc):
        return [
            {"id": hub.id, "name": hub.name, "slug": hub.slug}
            for hub in unified_doc.hubs.all()
        ]

    def get_created_by(self, unified_doc):
        if not unified_doc.created_by:
            return None
        user = unified_doc.created_by
        return {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "author_profile": user.author_profile.id if hasattr(user, "author_profile") and user.author_profile else None,
        }

    def get_documents(self, unified_doc):
        doc_type = unified_doc.document_type
        context = self.context
        
        try:
            if doc_type in RESEARCHHUB_POST_DOCUMENT_TYPES:
                return ResearchhubPostSerializer(
                    unified_doc.posts, many=True, context=context
                ).data
            elif doc_type == PAPER:
                return PaperSerializer(unified_doc.paper, context=context).data
            else:
                return None
        except Exception:
            return None

    def get_reviews(self, unified_doc):
        if not unified_doc.reviews.exists():
            return {"avg": 0.0, "count": 0}
        return unified_doc.get_review_details()

    def get_fundraise(self, unified_doc):
        if not unified_doc.fundraises.exists():
            return None
        
        fundraise = unified_doc.fundraises.first()
        if not fundraise:
            return None
        
        try:
            serializer = FundraiseSerializer(fundraise, context=self.context)
            return serializer.data
        except Exception:
            return None

    def get_grant(self, unified_doc):
        grant = unified_doc.grants.first()
        if not grant:
            return None
        
        try:
            serializer = GrantSerializer(grant, context=self.context)
            return serializer.data
        except Exception:
            return None

    def get_title(self, unified_doc):
        try:
            doc_type = unified_doc.document_type
            if doc_type in RESEARCHHUB_POST_DOCUMENT_TYPES:
                post = unified_doc.posts.first()
                return post.title if post else None
            elif doc_type == PAPER:
                return unified_doc.paper.title if unified_doc.paper else None
        except Exception:
            pass
        return None

    def get_slug(self, unified_doc):
        try:
            doc_type = unified_doc.document_type
            if doc_type in RESEARCHHUB_POST_DOCUMENT_TYPES:
                post = unified_doc.posts.first()
                return post.slug if post else None
            elif doc_type == PAPER:
                return unified_doc.paper.slug if unified_doc.paper else None
        except Exception:
            pass
        return None


class ListItemDetailSerializer(ListItemSerializer):
    unified_document = serializers.SerializerMethodField()

    class Meta(ListItemSerializer.Meta):
        fields = ListItemSerializer.Meta.fields + ["unified_document"]

    def get_unified_document(self, obj):
        try:
            return UnifiedDocumentForListSerializer(
                obj.unified_document,
                context=self.context,
            ).data
        except Exception:
            return {
                "id": obj.unified_document.id,
                "document_type": obj.unified_document.document_type,
                "is_removed": obj.unified_document.is_removed,
            }


class ToggleListItemResponseSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["added", "removed"])
    item = serializers.SerializerMethodField()
    success = serializers.BooleanField()

    def get_item(self, obj):
        item = obj.get("item")
        if item:
            return ListItemDetailSerializer(item, context=self.context).data
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
        return ListItemDetailSerializer(paginated_items, many=True, context=self.context).data


class UserCheckItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    unified_document_id = serializers.IntegerField()


class UserCheckListSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    is_public = serializers.BooleanField()
    items = UserCheckItemSerializer(many=True)


class UserCheckResponseSerializer(serializers.Serializer):
    lists = UserCheckListSerializer(many=True)


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
            items = list_obj.items.filter(is_removed=False).order_by("-created_date")
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