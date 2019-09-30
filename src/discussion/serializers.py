import rest_framework.serializers as serializers

from .models import Comment, Thread
from user.models import User


# TODO: Add isOwner permission and make is_public editable

class ThreadSerializer(serializers.ModelSerializer):
    created_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        read_only=False,
        default=serializers.CurrentUserDefault()
    )

    class Meta:
        fields = [
            'id',
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


class CommentSerializer(serializers.ModelSerializer):
    created_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        read_only=False,
        default=serializers.CurrentUserDefault()
    )

    class Meta:
        fields = [
            'text',
            'parent',
            'created_by',
        ]
        read_only_fields = [
            'is_public',
            'is_removed'
        ]
        model = Comment
