import rest_framework.serializers as rest_framework_serializers

from .models import Hub


class HubSerializer(rest_framework_serializers.ModelSerializer):
    class Meta:
        model = Hub
        fields = '__all__'
