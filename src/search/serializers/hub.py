from rest_framework import serializers

from hub.models import Hub


class HubDocumentSerializer(serializers.ModelSerializer):
    subscriber_count = serializers.SerializerMethodField()

    class Meta(object):
        model = Hub
        fields = [
            'id',
            'name',
            'acronym',
            'is_locked',
            'subscriber_count',
        ]
        read_only_fields = fields

    def get_subscriber_count(self, obj):
        return obj.subscriber_count
