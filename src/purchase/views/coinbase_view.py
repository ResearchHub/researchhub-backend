import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from purchase.serializers.coinbase_serializer import CoinbaseSessionSerializer
from purchase.services.coinbase_service import CoinbaseService

logger = logging.getLogger(__name__)


class CoinbaseSessionView(APIView):
    """
    View for creating Coinbase session tokens for Onramp/Offramp.
    https://docs.cdp.coinbase.com/onramp-&-offramp/secure-init-migration#secure-init-migration
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CoinbaseSessionSerializer

    def __init__(self, coinbase_service: CoinbaseService = None, **kwargs):
        super().__init__(**kwargs)
        self.coinbase_service = coinbase_service or CoinbaseService()

    def post(self, request, *args, **kwargs):
        """
        Create a Coinbase session token.

        Expected request body:
        {
            "addresses": [
                {
                    "address": "0x123...",
                    "blockchains": ["ethereum", "base"]
                }
            ],
            "assets": ["ETH", "USDC"]  // optional
        }
        """
        serializer = CoinbaseSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        addresses = data.get("addresses")
        assets = data.get("assets", None)

        try:
            session_data = self.coinbase_service.generate_session_token(
                addresses=addresses,
                assets=assets,
            )

            return Response(session_data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error creating Coinbase session token: {e}")
            return Response(
                {"error": "Failed to create session token"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
