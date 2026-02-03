import logging

from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from purchase.endaoment import EndaomentService
from purchase.related_models.endaoment_account_model import EndaomentAccount

logger = logging.getLogger(__name__)


class EndaomentViewSet(GenericViewSet):
    """
    ViewSet for funding operations.

    Provides endpoints related to Endaoment funds.
    """

    permission_classes = [IsAuthenticated]

    def dispatch(self, request, *args, **kwargs):
        self.service = kwargs.pop("service", None) or EndaomentService()
        return super().dispatch(request, *args, **kwargs)

    @action(detail=False, methods=["GET"])
    def funds(self, request: Request) -> Response:
        """
        List the user's funds (DAFs).
        """
        try:
            funds = self.service.get_user_funds(request.user)
            return Response(funds)
        except EndaomentAccount.DoesNotExist:
            return Response(
                {"detail": "No Endaoment connection found."},
                status=404,
            )
        except Exception as e:
            logger.exception(f"Failed to fetch Endaoment funds: {e}")
            raise APIException("Failed to fetch Endaoment funds")
