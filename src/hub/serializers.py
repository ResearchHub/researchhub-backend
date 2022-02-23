from rest_framework.serializers import ModelSerializer, SerializerMethodField

from researchhub_access_group.serializers import DynamicPermissionSerializer

from .models import Hub, HubCategory
from researchhub.serializers import DynamicModelFieldSerializer


class SimpleHubSerializer(ModelSerializer):
    editor_permission_groups = SerializerMethodField()

    class Meta:
        fields = [
            'editor_permission_groups',
            'hub_image',
            'id',
            'is_locked',
            'is_removed',
            'name',
            'slug',
        ]
        read_only_fields = [
            'editor_permission_groups'
        ]
        model = Hub

    def get_editor_permission_groups(self, hub_instance):
        context = self.context
        __context_fields = context.get(
            'hub_shs_get_editor_permission_groups',
            {}
        )
        context['rag_dps_get_user'] = {
            '_include_fields': [
                'author_profile',
                'id',
            ]
        }
        editor_groups = hub_instance.editor_permission_groups
        return DynamicPermissionSerializer(
            editor_groups,
            **__context_fields,
            context=context,
            many=True,
        ).data


class HubSerializer(ModelSerializer):
    editor_permission_groups = SerializerMethodField()

    class Meta:
        fields = [
            'category',
            'description',
            'discussion_count',
            'editor_permission_groups',
            'hub_image',
            'id',
            'is_locked',
            'is_removed',
            'name',
            'paper_count',
            'slug',
            'subscriber_count',
        ]
        read_only_fields = [
            'editor_permission_groups'
        ]
        model = Hub

    def get_editor_permission_groups(self, hub_instance):
        context = self.context
        __context_fields = context.get(
            'hub_shs_get_editor_permission_groups',
            {}
        )
        editor_groups = hub_instance.editor_permission_groups
        return DynamicPermissionSerializer(
            editor_groups,
            **__context_fields,
            context=context,
            many=True,
        ).data


class HubCategorySerializer(ModelSerializer):
    class Meta:
        fields = [
            'id',
            'category_name'
        ]
        model = HubCategory


class HubContributionSerializer(ModelSerializer):

    class Meta:
        model = Hub
        fields = [
            'comment_count',
            'hub_image',
            'id',
            'latest_comment_date',
            'latest_submission_date',
            'name',
            'submission_count',
            'support_count',
            'total_contribution_count',
        ]
        read_only_fields = [
            'comment_count',
            'hub_image',
            'id',
            'name',
            'submission_count',
            'support_count',
            'total_contribution_count',
        ]

class DynamicHubSerializer(DynamicModelFieldSerializer):
    editor_permission_groups = SerializerMethodField()

    class Meta:
        model = Hub
        fields = '__all__'

    def get_editor_permission_groups(self, hub_instance):
        context = self.context
        __context_fields = context.get(
            'hub_dhs_get_editor_permission_groups',
            {}
        )
        editor_groups = hub_instance.editor_permission_groups
        return DynamicPermissionSerializer(
            editor_groups,
            **__context_fields,
            context=context,
            many=True,
        ).data
