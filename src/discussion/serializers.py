import rest_framework.serializers as rest_framework_serializers

from .models import Thread


class ThreadSerializer(rest_framework_serializers.HyperlinkedModelSerializer):

    # TODO: Ensure user gets added to the thread when the form is submitted
    class Meta:
        fields = ['title', 'text']
        model = Thread
