from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from purchase.models import RscExchangeRate
from purchase.serializers import (
    RscPurchaseCheckoutSerializer,
    RscPurchasePreviewSerializer,
)


class RscPurchaseViewSet(GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"], url_path="preview")
    def preview(self, request):
        """
        Preview USD to RSC conversion.

        Query Parameters:
        - usd_amount: USD amount to convert to RSC

        Returns:
        - usd_amount: The USD amount provided
        - rsc_amount: Calculated RSC equivalent
        - exchange_rate: Current USD to RSC exchange rate
        - rate_timestamp: When the exchange rate was recorded
        """
        serializer = RscPurchasePreviewSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        usd_amount = serializer.validated_data["usd_amount"]

        try:
            # Get current exchange rate
            exchange_rate = RscExchangeRate.get_latest_exchange_rate()

            # Calculate RSC amount
            rsc_amount = RscExchangeRate.usd_to_rsc(float(usd_amount))

            # Get the timestamp of the latest exchange rate
            latest_rate_obj = (
                RscExchangeRate.objects.filter(target_currency="USD")
                .order_by("-created_date")
                .first()
            )

            rate_timestamp = (
                latest_rate_obj.created_date if latest_rate_obj else timezone.now()
            )

            return Response(
                {
                    "usd_amount": str(usd_amount),
                    "rsc_amount": str(round(Decimal(str(rsc_amount)), 2)),
                    "exchange_rate": str(exchange_rate),
                    "rate_timestamp": rate_timestamp.isoformat(),
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"error": f"Unable to calculate RSC amount: {str(e)}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
