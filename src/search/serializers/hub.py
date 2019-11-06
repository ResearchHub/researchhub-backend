from rest_framework import serializers

from .mixins import HighlightSerializerMixin
from hub.models import Hub


class HubDocumentSerializer(
    serializers.ModelSerializer,
    HighlightSerializerMixin
):
    highlight = serializers.SerializerMethodField()

    class Meta(object):
        model = Hub
        fields = [
            'id',
            'name',
            'is_locked',
            'created_date',
            'updated_date',
            'highlight',
        ]
        read_only_fields = fields
