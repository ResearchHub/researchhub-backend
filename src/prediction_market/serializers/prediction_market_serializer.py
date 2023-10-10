from rest_framework.serializers import ModelSerializer, SerializerMethodField

from prediction_market.models import PredictionMarket
from researchhub.serializers import DynamicModelFieldSerializer


class PredictionMarketSerializer(ModelSerializer):
    class Meta:
        model = PredictionMarket
        fields = "__all__"


class DynamicPredictionMarketSerializer(DynamicModelFieldSerializer):
    votes = SerializerMethodField()
    bets = SerializerMethodField()

    class Meta:
        model = PredictionMarket
        fields = ["id", "prediction_type", "end_date", "status", "votes", "bets"]

    def get_votes(self, obj):
        votes_for = obj.votes_for
        votes_against = obj.votes_against
        total_votes = votes_for + votes_against

        return {"total": total_votes, "yes": votes_for, "no": votes_against}

    def get_bets(self, obj):
        bets_for = obj.bets_for
        bets_against = obj.bets_against
        total_bets = bets_for + bets_against

        return {"total": total_bets, "yes": bets_for, "no": bets_against}
