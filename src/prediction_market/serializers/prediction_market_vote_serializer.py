from rest_framework.serializers import ModelSerializer, SerializerMethodField

from prediction_market.models import PredictionMarketVote
from researchhub.serializers import DynamicModelFieldSerializer
from user.serializers import DynamicUserSerializer


class PredictionMarketVoteSerializer(ModelSerializer):
    class Meta:
        model = PredictionMarketVote
        exclude = ("created_by",)  # Excluding the created_by field


class DynamicPredictionMarketVoteSerializer(DynamicModelFieldSerializer):
    created_by = SerializerMethodField()

    class Meta:
        model = PredictionMarketVote
        fields = [
            "id",
            "prediction_market",
            "vote",
            "bet_amount",
            "created_by",
            "created_date",
            "updated_date",
        ]

    def get_created_by(self, obj):
        context = self.context
        _context_fields = context.get("rhc_dcs_get_created_by", {})
        serializer = DynamicUserSerializer(
            obj.created_by, context=context, **_context_fields
        )
        return serializer.data
