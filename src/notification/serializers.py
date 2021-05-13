import rest_framework.serializers as serializers

from .models import Notification
from user.serializers import UserActions, UserSerializer


class NotificationSerializer(serializers.ModelSerializer):
    action_user = UserSerializer(read_only=True)
    paper = serializers.PrimaryKeyRelatedField(read_only=True)
    recipient = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    action = serializers.SerializerMethodField()
    paper_slug = serializers.SerializerMethodField()

    class Meta:
        fields = '__all__'
        model = Notification
        read_only_fields = [
            'id',
            'action',
            'action_user',
            'paper',
            'recipient',
            'created_date',
            'updated_date',
            'extra'
        ]

    def get_action(self, obj):
        return UserActions(data=[obj.action]).serialized

    def get_paper_slug(self, obj):
        paper = obj.paper
        if paper:
            return paper.slug
        return None
