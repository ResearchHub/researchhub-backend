from rest_framework import serializers

from hub.models import Hub


class HubDocumentSerializer(serializers.ModelSerializer):

    class Meta(object):
        model = Hub
        fields = [
            'id',
            'name',
            'acronym',
            'is_locked',
            'hub_image',
            'paper_count',
            'subscriber_count',
            'discussion_count',
        ]
        read_only_fields = fields
