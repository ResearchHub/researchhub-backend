from rest_framework import serializers

from .models import Hub
from utils.http import get_user_from_request


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
            'slug',
        ]
        read_only_fields = [
            'subscriber_count',
            'user_is_subscribed'
        ]
        model = Hub

    def get_subscriber_count(self, obj):
        return len(obj.subscribers.all())

    def get_user_is_subscribed(self, obj):
        user = get_user_from_request(self.context)
        return user in obj.subscribers.all()
