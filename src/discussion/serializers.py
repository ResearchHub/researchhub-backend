import rest_framework.serializers as rest_framework_serializers

from .models import Thread


class ThreadSerializer(rest_framework_serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Thread
