import rest_framework.serializers as serializers

from .models import Notification
from paper.serializers import PaperSerializer
from user.serializers import UserSerializer


class NotificationSerializer(serializers.ModelSerializer):
    paper = PaperSerializer()
    recipient = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    action_user = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )

    class Meta:
        fields = '__all__'
        model = Notification
