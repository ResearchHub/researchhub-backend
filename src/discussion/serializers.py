import rest_framework.serializers as serializers

from .models import Thread
from user.models import User


class ThreadSerializer(serializers.ModelSerializer):
    created_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        read_only=False,
        default=serializers.CurrentUserDefault()
    )

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
        read_only_fields = [
            'is_public',
            'is_removed'
        ]
        model = Thread
