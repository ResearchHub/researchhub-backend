from rest_framework import serializers
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from researchhub_document.serializers.researchhub_unified_document_serializer import (
    DynamicUnifiedDocumentSerializer,
)
from utils.serializers import DefaultAuthenticatedSerializer

from .models import List, ListItem


class ListSerializer(DefaultAuthenticatedSerializer):
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


_UNIFIED_DOC_CONTEXT = {
    "doc_duds_get_documents": {
        "_include_fields": [
            "id",
            "created_date",
            "title",
            "slug",
            "authors",
            "abstract",
            "doi",
            "image_url",
            "renderable_text",
            "document_type",
            "score",
            "discussion_count",
            "hubs",
            "created_by",
            "unified_document",
            "unified_document_id",
            "fundraise",
            "grant",
        ]
    },
    "doc_duds_get_hubs": {"_include_fields": ["id", "name", "slug"]},
    "doc_duds_get_created_by": {"_include_fields": ["id", "author_profile", "first_name", "last_name"]},
    "doc_duds_get_fundraise": {
        "_include_fields": [
            "id",
            "status",
            "goal_amount",
            "goal_currency",
            "start_date",
            "end_date",
            "amount_raised",
            "contributors",
            "created_by",
        ]
    },
    "doc_duds_get_grant": {
        "_include_fields": [
            "id",
            "status",
            "amount",
            "currency",
            "organization",
            "description",
            "start_date",
            "end_date",
            "created_by",
            "contacts",
            "applications",
        ]
    },
    "pap_dps_get_authors": {"_include_fields": ["id", "first_name", "last_name", "author_profile"]},
    "pap_dps_get_unified_document": {"_include_fields": ["id", "fundraise", "grant"]},
    "doc_dps_get_authors": {"_include_fields": ["id", "first_name", "last_name", "author_profile"]},
    "doc_dps_get_unified_document": {"_include_fields": ["id", "fundraise", "grant"]},
    "pch_dfs_get_contributors": {"_include_fields": ["id", "author_profile", "first_name", "last_name", "profile_image"]},
    "pch_dfs_get_created_by": {"_include_fields": ["id", "first_name", "last_name", "profile_image", "author_profile"]},
    "pch_dgs_get_created_by": {"_include_fields": ["id", "first_name", "last_name", "profile_image", "author_profile"]},
    "pch_dgs_get_contacts": {"_include_fields": ["id", "first_name", "last_name", "profile_image", "author_profile"]},
}


class ListItemSerializer(DefaultAuthenticatedSerializer):
    unified_document = serializers.PrimaryKeyRelatedField(
        queryset=ResearchhubUnifiedDocument.objects.filter(is_removed=False), required=True
    )

    class Meta:
        model = ListItem
        fields = ["id", "parent_list", "unified_document", "created_date", "created_by"]
        read_only_fields = ["id", "created_date", "created_by"]


class ListItemDetailSerializer(ListItemSerializer):
    unified_document_data = serializers.SerializerMethodField()

    class Meta(ListItemSerializer.Meta):
        fields = ListItemSerializer.Meta.fields + ["unified_document_data"]

    def get_unified_document_data(self, obj):
        context = {**self.context, **_UNIFIED_DOC_CONTEXT}
        try:
            return DynamicUnifiedDocumentSerializer(
                obj.unified_document,
                _include_fields=[
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
                ],
                context=context,
            ).data
        except Exception:
            return {
                "id": obj.unified_document.id,
                "document_type": obj.unified_document.document_type,
                "is_removed": obj.unified_document.is_removed,
            }

