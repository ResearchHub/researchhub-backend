from rest_framework.serializers import ModelSerializer

from reputation.related_models.paper_reward import PaperReward


class PaperRewardSerializer(ModelSerializer):
    class Meta:
        model = PaperReward
        fields = "__all__"
