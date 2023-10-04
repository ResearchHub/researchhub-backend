from django.db.models import Sum
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
        total_votes = obj.prediction_market_votes.count()
        votes_for = obj.prediction_market_votes.filter(vote=True).count()
        votes_against = total_votes - votes_for

        return {"total": total_votes, "yes": votes_for, "no": votes_against}

    def get_bets(self, obj):
        # sum bets for and against
        bets_for = (
            obj.prediction_market_votes.filter(
                vote=True, bet_amount__isnull=False
            ).aggregate(total_bet=Sum("bet_amount"))["total_bet"]
            or 0
        )

        bets_against = (
            obj.prediction_market_votes.filter(
                vote=False, bet_amount__isnull=False
            ).aggregate(total_bet=Sum("bet_amount"))["total_bet"]
            or 0
        )

        total_bets = bets_for + bets_against

        return {"total": total_bets, "yes": bets_for, "no": bets_against}
