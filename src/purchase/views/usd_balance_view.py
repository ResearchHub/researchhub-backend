from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from utils.throttles import THROTTLE_CLASSES


class UsdBalanceViewSet(viewsets.ViewSet):
    """ViewSet for USD balance operations."""

    permission_classes = [IsAuthenticated]
    throttle_classes = THROTTLE_CLASSES

    def list(self, request):
        """Get user's current USD balance in cents."""
        user = request.user
        balance_cents = user.get_usd_balance_cents()
        return Response({"balance_cents": balance_cents})
