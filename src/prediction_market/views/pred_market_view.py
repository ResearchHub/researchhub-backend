from rest_framework import viewsets
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from prediction_market.models import PredictionMarket
from prediction_market.serializers.prediction_market_serializer import (
    DynamicPredictionMarketSerializer,
    PredictionMarketSerializer,
)
from prediction_market.utils import create_prediction_market
from utils.throttles import THROTTLE_CLASSES


class PredictionMarketViewSet(viewsets.ModelViewSet):
    serializer_class = PredictionMarketSerializer
    throttle_classes = THROTTLE_CLASSES

    permission_classes = [
        IsAuthenticatedOrReadOnly,
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

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = DynamicPredictionMarketSerializer(instance)
        return Response(serializer.data)
