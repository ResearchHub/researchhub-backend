from rest_framework import serializers

from bullet_point.models import BulletPoint, Endorsement, Flag
from user.serializers import UserSerializer


class EndorsementSerializer(serializers.ModelSerializer):
    bullet_point = serializers.PrimaryKeyRelatedField(
        many=False,
        read_only=True
    )
    created_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
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
    created_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )

    class Meta:
        fields = [
            'bullet_point',
            'created_by',
            'created_date',
            'reason',
        ]
        model = Flag


class BulletPointSerializer(serializers.ModelSerializer):
    tail_created_by = serializers.SerializerMethodField()
    tail_editors = serializers.SerializerMethodField()
    created_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    editors = serializers.SerializerMethodField()
    endorsements = EndorsementSerializer(read_only=True, many=True)
    flags = FlagSerializer(read_only=True, many=True)

    class Meta:
        model = BulletPoint
        exclude = []
        read_only_fields = [
            'is_head',
            'is_tail',
            'previous',
            'tail',
        ]

    def get_tail_created_by(self, obj):
        if obj.is_tail:
            tail = obj
        else:
            tail = obj.tail
        return UserSerializer(tail.created_by).data

    def get_tail_editors(self, obj):
        if obj.is_tail:
            tail = obj
        else:
            tail = obj.tail
        return self.get_editors(tail)

    def get_editors(self, obj):
        return UserSerializer(obj.editors, many=True).data


class BulletPointTextOnlySerializer(serializers.ModelSerializer):
    paper = serializers.PrimaryKeyRelatedField(many=False, read_only=True)

    class Meta:
        model = BulletPoint
        fields = [
            'is_head',
            'is_public',
            'ordinal',
            'paper',
            'plain_text',
            'text',
        ]
        read_only_fields = fields
