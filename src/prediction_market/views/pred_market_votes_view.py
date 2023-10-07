from rest_framework import viewsets
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from prediction_market.models import PredictionMarket, PredictionMarketVote
from prediction_market.serializers.prediction_market_vote_serializer import (
    DynamicPredictionMarketVoteSerializer,
    PredictionMarketVoteSerializer,
)
from prediction_market.utils import get_or_create_prediction_market
from reputation.models import Contribution
from reputation.tasks import create_contribution, delete_contribution
from utils.throttles import THROTTLE_CLASSES


class PredictionMarketVoteViewSet(viewsets.ModelViewSet):
    serializer_class = PredictionMarketVoteSerializer
    throttle_classes = THROTTLE_CLASSES

    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = (OrderingFilter,)
    order_fields = ["created_date", "vote", "bet_amount"]
    ordering = ("-created_date",)
    queryset = PredictionMarketVote.objects.all()

    def create(self, request, *args, **kwargs):
        user = request.user
        data = request.data

        pred_mkt_id = data.get("prediction_market_id")
        paper_id = data.get("paper_id")
        vote = data.get("vote")
        bet_amount = data.get("bet_amount")

        # validate data
        if vote is None:
            return Response({"message": "vote is required"}, status=400)
        if pred_mkt_id is None or pred_mkt_id == "":
            # check if paper_id is provided
            if paper_id is None:
                return Response(
                    {"message": "prediction_market_id or paper_id is required"},
                    status=400,
                )

            # get prediction market, or create one if it doesn't exist
            prediction_market = get_or_create_prediction_market(paper_id)
            pred_mkt_id = prediction_market.id

        try:
            prediction_market = PredictionMarket.objects.get(id=pred_mkt_id)
        except PredictionMarket.DoesNotExist:
            return Response({"message": "Prediction market does not exist"}, status=400)

        # check if user has voted before
        prev_vote = PredictionMarketVote.objects.filter(
            created_by=user, prediction_market=prediction_market
        ).first()

        if prev_vote is not None:
            # update vote
            prev_vote.vote = vote
            prev_vote.bet_amount = bet_amount
            prev_vote.save()
            prediction_market_vote = prev_vote
        else:
            # create vote
            prediction_market_vote = PredictionMarketVote.objects.create(
                created_by=user,
                prediction_market=prediction_market,
                vote=vote,
                bet_amount=bet_amount,
            )

            # track as contribution if it's a new vote
            create_contribution.apply_async(
                (
                    Contribution.REPLICATION_VOTE,
                    {
                        "app_label": "prediction_market",
                        "model": "predictionmarketvote",
                    },
                    request.user.id,
                    prediction_market.unified_document.id,
                    prediction_market_vote.id,
                ),
                priority=1,
                countdown=10,
            )

        context = self._get_retrieve_context()
        data = DynamicPredictionMarketVoteSerializer(
            prediction_market_vote, context=context
        ).data
        return Response(data, status=200)

    def _get_retrieve_context(self):
        context = self.get_serializer_context()
        context = {
            **context,
            "rhc_dcs_get_created_by": {
                "_include_fields": (
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                    "editor_of",
                )
            },
            "usr_dus_get_author_profile": {
                "_include_fields": (
                    "id",
                    "first_name",
                    "last_name",
                    "created_date",
                    "updated_date",
                    "profile_image",
                )
            },
        }
        return context

    def list(self, request, *args, **kwargs):
        pred_mkt_id = request.query_params.get("prediction_market_id")
        is_user_vote = request.query_params.get("is_user_vote")

        user = request.user

        if pred_mkt_id is None:
            return Response({"message": "prediction_market_id is required"}, status=400)
        try:
            prediction_market = PredictionMarket.objects.get(id=pred_mkt_id)
        except PredictionMarket.DoesNotExist:
            return Response({"message": "Prediction market does not exist"}, status=400)
        queryset = PredictionMarketVote.objects.filter(
            prediction_market=prediction_market
        )

        if is_user_vote is not None:
            queryset = queryset.filter(created_by=user)

        # Apply ordering
        ordering = OrderingFilter().get_ordering(request, queryset, self)
        if ordering:
            queryset = queryset.order_by(*ordering)

        context = self._get_retrieve_context()
        serializer = DynamicPredictionMarketVoteSerializer(
            queryset, many=True, context=context
        )
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        user = request.user
        vote = self.get_object()
        if vote.created_by != user:
            return Response(
                {"message": "You are not authorized to delete this vote"},
                status=403
            )

        prediction_market = vote.prediction_market

        delete_contribution.apply_async(
            (
                Contribution.REPLICATION_VOTE,
                {
                    "app_label": "prediction_market",
                    "model": "predictionmarketvote",
                },
                prediction_market.unified_document.id,
                vote.id,
            ),
            priority=1,
            countdown=10,
        )

        vote.delete()

        return Response(status=204)
