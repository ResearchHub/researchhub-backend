import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from purchase.circle import CircleWalletService
from purchase.circle.client import CircleWalletCreationError, CircleWalletNotReadyError

logger = logging.getLogger(__name__)


class DepositAddressView(APIView):
    """
    API endpoint to get (or lazily provision) the user's Circle deposit address.

    GET /api/wallet/deposit-address/

    Responses:
        200: {"address": "0x...", "provisioning": false}
        202: {"message": "Wallet is being provisioned. Please retry.",
              "retry_after": 3}
        500: {"detail": "Failed to provision deposit address"}
    """

    permission_classes = [IsAuthenticated]

    def dispatch(self, request, *args, **kwargs):
        self.service = kwargs.pop("service", None) or CircleWalletService()
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: Request) -> Response:
        try:
            result = self.service.get_or_create_deposit_address(request.user)
            return Response(
                {
                    "address": result.address,
                    "provisioning": result.provisioning,
                }
            )
        except CircleWalletNotReadyError:
            return Response(
                {
                    "message": "Wallet is being provisioned. Please retry.",
                    "retry_after": 3,
                },
                status=status.HTTP_202_ACCEPTED,
                headers={"Retry-After": "3"},
            )
        except CircleWalletCreationError:
            logger.exception(
                "Circle wallet creation failed for user %s", request.user.id
            )
            return Response(
                {"detail": "Failed to provision deposit address"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception:
            logger.exception(
                "Unexpected error provisioning deposit address for user %s",
                request.user.id,
            )
            return Response(
                {"detail": "Failed to provision deposit address"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
