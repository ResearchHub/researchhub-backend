import rest_framework.serializers as serializers

from .models import Summary, Vote
from user.serializers import UserSerializer
from utils.http import get_user_from_request


class PreviousSummarySerializer(serializers.ModelSerializer):
    class Meta:
        fields = '__all__'
        model = Summary


class SummarySerializer(serializers.ModelSerializer):
    proposed_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    previous__summary = serializers.SerializerMethodField()
    paper_title = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    promoted = serializers.SerializerMethodField()
    paper_slug = serializers.SerializerMethodField()

    class Meta:
        fields = '__all__'
        model = Summary

    def get_paper_title(self, obj):
        return obj.paper.title

    def get_previous__summary(self, obj):
        if obj.previous:
            previous = PreviousSummarySerializer(obj.previous).data
            return previous['summary']
        else:
            return None

    def get_score(self, obj):
        return obj.calculate_score()

    def get_user_vote(self, obj):
        user = get_user_from_request(self.context)
        if user and not user.is_anonymous:
            vote = obj.votes.filter(created_by=user)
            if vote.exists():
                return SummaryVoteSerializer(vote.last()).data
            return False
        return False

    def get_promoted(self, obj):
        if self.context.get('exclude_promoted_score', False):
            return None
        return obj.get_promoted_score()

    def get_paper_slug(self, obj):
        return obj.paper.slug


class SummaryVoteSerializer(serializers.ModelSerializer):
    summary = serializers.SerializerMethodField()

    class Meta:
        fields = [
            'id',
            'created_by',
            'created_date',
            'vote_type',
            'summary',
        ]
        model = Vote

    def get_summary(self, obj):
        if self.context.get('include_summary_data', False):
            serializer = SummarySerializer(obj.summary)
            return serializer.data
        return None
