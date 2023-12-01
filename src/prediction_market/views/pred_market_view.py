from rest_framework import viewsets
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response

from prediction_market.models import PredictionMarket
from prediction_market.permissions import IsModeratorOrReadOnly
from prediction_market.serializers.prediction_market_serializer import (
    DynamicPredictionMarketSerializer,
)
from prediction_market.utils import create_prediction_market
from utils.throttles import THROTTLE_CLASSES


class PredictionMarketViewSet(viewsets.ModelViewSet):
    serializer_class = DynamicPredictionMarketSerializer
    throttle_classes = THROTTLE_CLASSES

    permission_classes = [
        IsModeratorOrReadOnly,
    ]
    filter_backends = (OrderingFilter,)
    order_fields = "__all__"
    ordering = ("-created_date",)
    queryset = PredictionMarket.objects.all()

    def create(self, request, *args, **kwargs):
        data = request.data

        paper_id = data.get("paper_id")
        if paper_id is None:
            return Response({"message": "paper_id is required"}, status=400)

        try:
            prediction_market = create_prediction_market(paper_id)
        except Exception as e:
            return Response({"message": str(e)}, status=400)

        data = DynamicPredictionMarketSerializer(prediction_market).data
        return Response(data, status=200)

    # Disabling any updating/deletion of prediction markets for now

    def update(self, request, *args, **kwargs):
        raise MethodNotAllowed("PUT")

    def partial_update(self, request, *args, **kwargs):
        raise MethodNotAllowed("PATCH")

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE")
