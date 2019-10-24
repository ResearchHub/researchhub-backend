import rest_framework.serializers as rest_framework_serializers

from .models import Hub


class HubSerializer(rest_framework_serializers.ModelSerializer):

    class Meta:
        fields = [
            'name',
            'is_locked',
            'subscribers',
        ]
        read_only_fields = [
            'subscribers'
        ]
        model = Hub
