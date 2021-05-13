from rest_framework import serializers

from bullet_point.models import BulletPoint, Endorsement, Flag, Vote
from user.serializers import UserSerializer
from utils.http import get_user_from_request


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
    score = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    promoted = serializers.SerializerMethodField()
    paper_slug = serializers.SerializerMethodField()
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

    def get_score(self, obj):
        return obj.calculate_score()

    def get_user_vote(self, obj):
        user = get_user_from_request(self.context)
        if user and not user.is_anonymous:
            vote = obj.votes.filter(created_by=user)
            if vote.exists():
                return BulletPointVoteSerializer(vote.last()).data
            return False
        return False

    def get_promoted(self, obj):
        if self.context.get('exclude_promoted_score', False):
            return None
        return obj.get_promoted_score()

    def get_paper_slug(self, obj):
        if obj.paper:
            return obj.paper.slug


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


class BulletPointVoteSerializer(serializers.ModelSerializer):
    bullet_point = serializers.SerializerMethodField()

    class Meta:
        fields = [
            'id',
            'created_by',
            'created_date',
            'vote_type',
            'bullet_point',
        ]
        model = Vote

    def get_bullet_point(self, obj):
        if self.context.get('include_bullet_data', False):
            serializer = BulletPointSerializer(obj.bulletpoint)
            return serializer.data
        return None
