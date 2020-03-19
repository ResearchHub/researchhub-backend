import rest_framework.serializers as serializers

from .models import Notification
from user.serializers import UserActions, UserSerializer


class NotificationSerializer(serializers.ModelSerializer):
    action = serializers.SerializerMethodField()
    action_user = serializers.PrimaryKeyRelatedField(read_only=True)
    recipient = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    paper = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        fields = '__all__'
        model = Notification
        read_only_fields = [
            'id',
            'paper',
            'recipient',
            'created_date',
            'updated_date',
        ]

    def get_action(self, obj):
        return UserActions(data=[obj.action]).serialized
