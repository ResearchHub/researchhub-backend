from rest_framework import serializers
from rest_framework.fields import SerializerMethodField

from researchhub_access_group.serializers import DynamicPermissionSerializer

from .models import Hub, HubCategory
from researchhub.serializers import DynamicModelFieldSerializer


class SimpleHubSerializer(serializers.ModelSerializer):
    class Meta:
        fields = [
            'id',
            'name',
            'is_locked',
            'slug',
            'is_removed',
            'hub_image'
        ]
        model = Hub


class HubSerializer(serializers.ModelSerializer):
    class Meta:
        fields = [
            'category',
            'description',
            'discussion_count',
            'hub_image',
            'id',
            'is_locked',
            'is_removed',
            'name',
            'paper_count',
            'slug',
            'subscriber_count',
        ]
        model = Hub


class HubCategorySerializer(serializers.ModelSerializer):
    class Meta:
        fields = [
            'id',
            'category_name'
        ]
        model = HubCategory


class DynamicHubSerializer(DynamicModelFieldSerializer):
    class Meta:
        model = Hub
        fields = '__all__'
        read_only_fields = ['editor_permission_groups']

    def get_editor_permission_groups(self, hub_instance):
        context = self.context
        __context_fields = context.get(
            'hub_dhs_get_editor_permission_groups',
            {}
        )
        return DynamicPermissionSerializer(
            hub_instance.editor_permission_groups,
            **__context_fields,
            conext=context,
            many=True,
        )
