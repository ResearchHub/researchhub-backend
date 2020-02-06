import rest_framework.serializers as serializers

from .models import Summary
from user.serializers import UserSerializer


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
