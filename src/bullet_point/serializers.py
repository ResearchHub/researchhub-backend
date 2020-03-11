from rest_framework import serializers

from bullet_point.models import BulletPoint, Endorsement, Flag
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


class EndorsementSerializer(serializers.ModelSerializer):
    bullet_point = serializers.PrimaryKeyRelatedField(
        many=False,
        read_only=True
    )

    class Meta:
        fields = [
            'bullet_point',
            'created_by',
            'created_date',
        ]
        model = Endorsement


class FlagSerializer(serializers.ModelSerializer):
    bullet_point = serializers.PrimaryKeyRelatedField(
        many=False,
        read_only=True
    )

    class Meta:
        fields = [
            'bullet_point',
            'created_by',
            'created_date',
            'reason',
        ]
        model = Flag
