import logging

from django.shortcuts import redirect
from rest_framework.exceptions import APIException, NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from purchase.endaoment import EndaomentService

logger = logging.getLogger(__name__)


class EndaomentConnectView(APIView):
    """
    API endpoint for initiating the Endaoment OAuth flow.

    Also see: https://docs.endaoment.org/developers/quickstart/login-user
    """

    permission_classes = [IsAuthenticated]

    def dispatch(self, request, *args, **kwargs):
        self.service = kwargs.pop("service", None) or EndaomentService()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request: Request) -> Response:
        """
        Initiate Endaoment OAuth flow by returning the Endaoment authorization URL
        (https://auth.endaoment.org/auth?...).
        """
        try:
            # The `return_url` is an optional parameter to redirect after OAuth completion
            return_url = request.data.get("return_url")
            auth_url = self.service.get_authorization_url(request.user.id, return_url)

            return Response(
                {
                    "auth_url": auth_url,
                }
            )
        except Exception as e:
            logger.warning(f"Failed to initiate Endaoment connection: {e}")
            raise APIException("Failed to initiate Endaoment connection")


class EndaomentCallbackView(APIView):
    """
    Handle Endaoment OAuth callback redirect.
    """

    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        self.service = kwargs.pop("service", None) or EndaomentService()
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: Request):
        """
        Handle Endaoment OAuth callback.

        Query params:
            code: Authorization code (on success)
            state: Signed state token
            error: Error code (on user cancellation or error)
        """
        result = self.service.process_callback(
            code=request.query_params.get("code"),
            state=request.query_params.get("state", ""),
            error=request.query_params.get("error"),
        )

        redirect_url = self.service.build_redirect_url(
            error=result.error, return_url=result.return_url
        )

        return redirect(redirect_url)


class EndaomentDisconnectView(APIView):
    """
    API endpoint for disconnecting a user's Endaoment account.
    """

    permission_classes = [IsAuthenticated]

    def dispatch(self, request, *args, **kwargs):
        self.service = kwargs.pop("service", None) or EndaomentService()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request: Request) -> Response:
        """
        Disconnect the authenticated user's Endaoment account.
        """
        try:
            disconnected = self.service.disconnect(request.user)
        except Exception as e:
            logger.warning(f"Failed to disconnect Endaoment account: {e}")
            raise APIException("Failed to disconnect Endaoment account")

        if not disconnected:
            raise NotFound("No Endaoment connection found to disconnect.")
        return Response(status=204)


class EndaomentStatusView(APIView):
    """
    Provides an endpoint to check if user has an Endaoment connection.
    """

    permission_classes = [IsAuthenticated]

    def dispatch(self, request, *args, **kwargs):
        self.service = kwargs.pop("service", None) or EndaomentService()
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: Request) -> Response:
        """
        Check if the authenticated user has an Endaoment connection.
        """
        connection_status = self.service.get_connection_status(request.user)

        return Response(
            {
                "connected": connection_status.connected,
            }
        )
