import rest_framework.serializers as rest_framework_serializers

from .models import Paper


class PaperSerializer(rest_framework_serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Paper
