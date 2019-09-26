import rest_framework.serializers as serializers

from .models import Paper
from user.models import User


class PaperSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        read_only=False,
        default=serializers.CurrentUserDefault()
    )

    class Meta:
        fields = [
            'title',
            'uploaded_by',
            'authors',
            'paper_publish_date',
            'doi',
            'hubs',
            'url',
            'uploaded_date',
            'updated_date',
        ]
        model = Paper
