import rest_framework.serializers as serializers

from .models import Comment, Thread, Vote
from user.serializers import UserSerializer


# TODO: Add isOwner permission and make is_public editable

class ThreadSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    comment_count = serializers.SerializerMethodField()

    class Meta:
        fields = [
            'id',
            'title',
            'text',
            'paper',
            'created_by',
            'created_date',
            'is_public',
            'is_removed',
            'comment_count'
        ]
        read_only_fields = [
            'is_public',
            'is_removed'
        ]
        model = Thread

    def get_comment_count(self, obj):
        count = len(obj.comments.all())
        return count


class CommentSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )

    class Meta:
        fields = [
            'id',
            'created_by',
            'created_date',
            'updated_date',
            'is_public',
            'is_removed',
            'text',
            'parent'
        ]
        read_only_fields = [
            'is_public',
            'is_removed'
        ]
        model = Comment


class VoteSerializer(serializers.ModelSerializer):

    class Meta:
        fiels = '__all__'
        model = Vote
