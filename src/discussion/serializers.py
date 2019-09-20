import rest_framework.serializers as rest_framework_serializers

from .models import Thread


class ThreadSerializer(rest_framework_serializers.ModelSerializer):

    # TODO: Ensure user gets added to the thread when the form is submitted
    class Meta:
        fields = [
            'title',
            'text',
            'paper',
            'created_by',
            'created_date',
            'is_public',
            'is_removed'
        ]
        model = Thread
