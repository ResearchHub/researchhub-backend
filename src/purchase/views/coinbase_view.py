import logging
from typing import Optional

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from purchase.serializers.coinbase_serializer import CoinbaseSerializer
from purchase.services.coinbase_service import CoinbaseService
from utils.http import get_client_ip

logger = logging.getLogger(__name__)


class CoinbaseViewSet(viewsets.ViewSet):
    """
    ViewSet for Coinbase-related operations.
    """

    permission_classes = [IsAuthenticated]

    def __init__(self, coinbase_service: Optional[CoinbaseService] = None, **kwargs):
        super().__init__(**kwargs)
        self.coinbase_service = coinbase_service or CoinbaseService()

    @action(detail=False, methods=["post", "options"], url_path="create-onramp")
    @CoinbaseService.secure_coinbase_cors
    def create_onramp(self, request):
        """
        Generate a Coinbase Onramp URL for the authenticated user.

        Expected request body:
        {
            "addresses": [
                {
                    "address": "0x123...",
                    "blockchains": ["base", "ethereum"]
                }
            ],
            "assets": ["ETH", "USDC"],  # optional
            "default_network": "base",  # optional
            "preset_fiat_amount": 100,  # optional
            "default_asset": "ETH"  # optional
        }
        """
        serializer = CoinbaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        client_ip = get_client_ip(request)

        if not client_ip:
            logger.error("Unable to determine client IP for Coinbase Onramp request")
            return Response(
                {"error": "Unable to determine client IP for security verification"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            onramp_url = self.coinbase_service.generate_onramp_url(
                addresses=data["addresses"],
                assets=data.get("assets"),
                default_network=data.get("default_network"),
                preset_fiat_amount=data.get("preset_fiat_amount"),
                preset_crypto_amount=data.get("preset_crypto_amount"),
                default_asset=data.get("default_asset"),
                client_ip=client_ip,
            )

            return Response(
                {
                    "onramp_url": onramp_url,
                    "expires_in_seconds": 300,
                    "test_ip": client_ip,  # 5 minutes
                },
                status=status.HTTP_200_OK,
            )
        except ValueError as e:
            logger.error(f"Validation error generating onramp URL: {e}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(f"Error generating onramp URL: {e}")
            return Response(
                {"error": "Failed to generate onramp URL"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
