
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny

from purchase.models import (
    RscExchangeRate,
)
from purchase.serializers import (
    RscExchangeRateSerializer,
)

class RscExchangeRatePagination(PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 10


class RscExchangeRateViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RscExchangeRate.objects.all()
    serializer_class = RscExchangeRateSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    pagination_class = RscExchangeRatePagination
    filterset_fields = [
        "price_source",
    ]
