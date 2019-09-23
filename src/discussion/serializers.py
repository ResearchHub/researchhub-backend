import rest_framework.serializers as serializers

from .models import Thread


class ThreadSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(
        read_only=True,
        default=serializers.CurrentUserDefault()
    )

    class Meta:
        fields = [
            'user',
            'title',
            'text',
            'paper',
            'created_by',
            'created_date',
            'is_public',
            'is_removed'
        ]
        model = Thread
