from django.contrib.admin.options import get_content_type_for_model
import rest_framework.serializers as serializers

from .models import Comment, Thread, Reply
from user.serializers import UserSerializer


# TODO: Add isOwner permission and make is_public editable

class ReplySerializer(serializers.ModelSerializer):
    created_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    parent = serializers.PrimaryKeyRelatedField(
        queryset=Comment.objects.all(),
        many=False,
        read_only=False
    )

    class Meta:
        fields = [
            'id',
            'created_by',
            'created_date',
            'is_public',
            'is_removed',
            'parent',
            'text',
            'updated_date',
            'was_edited',
        ]
        read_only_fields = [
            'is_public',
            'is_removed',
        ]
        model = Reply


class CommentSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    reply_count = serializers.SerializerMethodField()
    replies = ReplySerializer(read_only=True, many=True)

    class Meta:
        fields = [
            'id',
            'created_by',
            'created_date',
            'is_public',
            'is_removed',
            'parent',
            'reply_count',
            'replies',
            'text',
            'updated_date',
            'was_edited',
        ]
        read_only_fields = [
            'is_public',
            'is_removed',
            'reply_count',
            'replies',
        ]
        model = Comment

    def get_replies(self, obj):
        replies = Reply.objects.filter(
            content_type=get_content_type_for_model(obj),
            object_id=obj.id
        )
        return replies

    def get_reply_count(self, obj):
        replies = self.get_replies(obj)
        count = len(replies)
        return count


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
            'comment_count',
            'created_by',
            'created_date',
            'is_public',
            'is_removed',
            'was_edited',
        ]
        read_only_fields = [
            'is_public',
            'is_removed'
        ]
        model = Thread

    def get_comment_count(self, obj):
        count = len(obj.comments.all())
        return count
