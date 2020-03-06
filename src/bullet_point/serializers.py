from rest_framework import serializers

from bullet_point.models import BulletPoint
from user.serializers import UserSerializer


class BulletPointSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )

    class Meta:
        model = BulletPoint
        exclude = []
        read_only_fields = []

    def get_endorsements(self, obj):
        pass

    def get_flags(self, obj):
        pass
