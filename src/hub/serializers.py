from rest_framework import serializers

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
            'id',
            'name',
            'is_locked',
            'subscriber_count',
            'paper_count',
            'discussion_count',
            'slug',
            'description',
            'hub_image',
            'category',
            'is_removed',
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
