from rest_framework import serializers

from hub.models import Hub


class HubDocumentSerializer(serializers.ModelSerializer):
    # paper_count = serializers.SerializerMethodField()
    # subscriber_count = serializers.SerializerMethodField()

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

    # def get_paper_count(self, obj):
    #     return obj.paper_count

    # def get_subscriber_count(self, obj):
    #     return obj.subscriber_count
