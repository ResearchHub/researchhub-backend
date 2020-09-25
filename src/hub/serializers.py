from rest_framework import serializers

from .models import Hub, HubCategory
from utils.http import get_user_from_request


class SimpleHubSerializer(serializers.ModelSerializer):
    class Meta:
        fields = [
            'id',
            'name',
            'is_locked',
            'slug',
        ]
        model = Hub


class HubSerializer(serializers.ModelSerializer):
    subscriber_count = serializers.SerializerMethodField()
    user_is_subscribed = serializers.SerializerMethodField()

    class Meta:
        fields = [
            'id',
            'name',
            'is_locked',
            'subscriber_count',
            'user_is_subscribed',
            'paper_count',
            'discussion_count',
            'slug',
            'description',
            'hub_image',
            'category'
        ]
        read_only_fields = [
            'subscriber_count',
            'user_is_subscribed'
        ]
        model = Hub

    def get_subscriber_count(self, obj):
        return obj.subscribers.count()

    def get_user_is_subscribed(self, obj):
        user = get_user_from_request(self.context)
        return user in obj.subscribers.all()


class HubCategorySerializer(serializers.ModelSerializer):
    class Meta:
        fields = [
            'id',
            'category_name'
        ]
        model = HubCategory
