from .base import BaseModelSerializer
from hub.models import Hub


class HubDocumentSerializer(BaseModelSerializer):

    class Meta(object):
        model = Hub
        fields = [
            'id',
            'name',
            'is_locked',
            'created_date',
            'updated_date',
        ]
