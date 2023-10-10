from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from prediction_market.filters import PredictionMarketVoteFilter
from prediction_market.models import PredictionMarket, PredictionMarketVote
from prediction_market.serializers.prediction_market_vote_serializer import (
    DynamicPredictionMarketVoteSerializer,
    PredictionMarketVoteSerializer,
)
from prediction_market.signals import soft_deleted, vote_saved
from prediction_market.utils import get_or_create_prediction_market
from reputation.models import Contribution
from reputation.tasks import create_contribution, delete_contribution
from utils.throttles import THROTTLE_CLASSES


class PredictionMarketVoteViewSet(viewsets.ModelViewSet):
    serializer_class = PredictionMarketVoteSerializer
    throttle_classes = THROTTLE_CLASSES

    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = (
        DjangoFilterBackend,
        OrderingFilter,
    )
    filterset_class = PredictionMarketVoteFilter

    order_fields = ["created_date", "vote", "bet_amount"]
    ordering = ("-created_date",)
    queryset = PredictionMarketVote.objects.exclude(
        vote=PredictionMarketVote.VOTE_NEUTRAL
    )

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
        create_new_contribution = False

        if prev_vote is not None:
            prev_vote_value = prev_vote.vote
            prev_bet_amount = prev_vote.bet_amount

            # update vote
            prev_vote.vote = vote
            prev_vote.bet_amount = bet_amount
            prev_vote.save()
            prediction_market_vote = prev_vote

            # if we're changing the vote from neutral to non-neutral, track as contribution
            if (
                prev_vote_value == PredictionMarketVote.VOTE_NEUTRAL
                and vote != PredictionMarketVote.VOTE_NEUTRAL
            ):
                create_new_contribution = True

            # send signal to update prediction market
            vote_saved.send(
                sender=PredictionMarketVote,
                instance=prev_vote,
                created=False,
                previous_vote_value=prev_vote_value,
                previous_bet_amount=prev_bet_amount,
            )
        else:
            # create vote
            prediction_market_vote = PredictionMarketVote.objects.create(
                created_by=user,
                prediction_market=prediction_market,
                vote=vote,
                bet_amount=bet_amount,
            )
            create_new_contribution = True

            # send signal to update prediction market
            vote_saved.send(
                sender=PredictionMarketVote,
                instance=prediction_market_vote,
                created=True,
                previous_vote_value=None,
                previous_bet_amount=None,
            )

        if create_new_contribution:
            # track as contribution if it's a new non-neutral vote
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

    def get_serializer_class(self):
        if self.action == "list":
            return DynamicPredictionMarketVoteSerializer
        return super().get_serializer_class()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action == "list":
            context.update(self._get_retrieve_context())
        return context

    def _get_retrieve_context(self):
        context = {
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

    @action(
        detail=True, methods=["post"], permission_classes=(IsAuthenticatedOrReadOnly,)
    )
    def soft_delete(self, request, *args, **kwargs):
        user = request.user
        vote = self.get_object()
        if vote.created_by != user:
            return Response(
                {"message": "You are not authorized to delete this vote"}, status=403
            )

        prediction_market = vote.prediction_market
        prev_vote_value = vote.vote
        prev_bet_amount = vote.bet_amount

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

        vote.vote = PredictionMarketVote.VOTE_NEUTRAL
        vote.save()

        # send signal to update prediction market
        soft_deleted.send(
            sender=PredictionMarketVote,
            instance=vote,
            previous_vote_value=prev_vote_value,
            previous_bet_amount=prev_bet_amount,
        )

        return Response(status=204)
