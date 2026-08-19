import logging

from rest_framework.serializers import (
    ModelSerializer,
    SerializerMethodField,
)

from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_access_group.serializers import DynamicPermissionSerializer

from .models import Hub

logger = logging.getLogger(__name__)


class SimpleHubSerializer(ModelSerializer):
    editor_permission_groups = SerializerMethodField()

    class Meta:
        fields = [
            "editor_permission_groups",
            "hub_image",
            "id",
            "is_locked",
            "is_removed",
            "name",
            "slug",
            "namespace",
        ]
        read_only_fields = ["editor_permission_groups"]
        model = Hub

    def get_editor_permission_groups(self, hub_instance):
        context = self.context
        __context_fields = context.get("hub_shs_get_editor_permission_groups", {})
        context["rag_dps_get_user"] = {
            "_include_fields": [
                "author_profile",
                "id",
            ]
        }

        editor_groups = hub_instance.editor_permission_groups
        return DynamicPermissionSerializer(
            editor_groups,
            _exclude_fields=["source"],
            context=context,
            many=True,
            **__context_fields,
        ).data


class HubSerializer(ModelSerializer):
    editor_permission_groups = SerializerMethodField()
    category = SerializerMethodField()

    class Meta:
        fields = [
            "category",
            "description",
            "discussion_count",
            "editor_permission_groups",
            "hub_image",
            "id",
            "is_locked",
            "is_removed",
            "name",
            "paper_count",
            "slug",
            "subscriber_count",
            "namespace",
        ]
        read_only_fields = ["editor_permission_groups", "category"]
        model = Hub

    def get_category(self, obj):
        # Check if we have category mapping in context
        hub_category_mapping = self.context.get("hub_category_mapping", {})
        if hub_category_mapping and obj.slug in hub_category_mapping:
            return hub_category_mapping[obj.slug]
        return None

    def get_editor_permission_groups(self, hub_instance):
        context = self.context
        __context_fields = context.get("hub_shs_get_editor_permission_groups", {})
        editor_groups = hub_instance.editor_permission_groups
        return DynamicPermissionSerializer(
            editor_groups,
            **__context_fields,
            context=context,
            many=True,
        ).data


class DynamicHubSerializer(DynamicModelFieldSerializer):
    editor_permission_groups = SerializerMethodField()
    relevancy_score = SerializerMethodField()

    class Meta:
        model = Hub
        fields = "__all__"

    def get_editor_permission_groups(self, hub_instance):
        context = self.context
        __context_fields = context.get("hub_dhs_get_editor_permission_groups", {})
        editor_groups = hub_instance.editor_permission_groups
        return DynamicPermissionSerializer(
            editor_groups,
            **__context_fields,
            context=context,
            many=True,
        ).data

    def get_relevancy_score(self, hub_instance):
        concept = hub_instance.concept

        if not concept:
            return 0

        unified_document = self.context.get("unified_document", None)
        related_concept_membership = concept.through_unified_document.filter(
            unified_document=unified_document
        )

        if related_concept_membership.exists():
            return related_concept_membership.first().relevancy_score
