from dataclasses import asdict
from functools import wraps

from django.conf import settings
from django.http import Http404, JsonResponse
from oauth2_provider.views import IntrospectTokenView, OAuthServerMetadataView
from oauthlib.common import Request as OAuthLibRequest
from rest_framework.response import Response
from rest_framework.views import APIView

from oauth.services.authorization_server_service import (
    AuthorizationError,
    OAuthAuthorizationServerService,
)


def oauth_enabled(view):
    """
    Hides an OAuth endpoint while `OAUTH_ENABLED` is off.
    """

    # wraps() keeps view attributes such as DOT's `csrf_exempt`
    @wraps(view)
    def wrapped_view(request, *args, **kwargs):
        if not settings.OAUTH_ENABLED:
            raise Http404
        return view(request, *args, **kwargs)

    return wrapped_view


class AuthorizationServerMetadataView(OAuthServerMetadataView):
    """
    Returns OAuth 2.0 authorization server metadata (RFC 8414).
    """

    def _get_endpoint_url(self, request, view_name, required=False):
        if view_name == "authorize":
            # The consent page is hosted on the frontend:
            return f"{settings.BASE_FRONTEND_URL}/oauth/authorize"
        return super()._get_endpoint_url(request, view_name, required)


class IntrospectionView(IntrospectTokenView):
    """
    Describes an access token to the MCP server (RFC 7662), which authenticates
    as a confidential client.
    """

    # Only allow POST, so tokens are not exposed in URLs or access logs
    http_method_names = ["post"]

    def authenticate_client(self, request):
        """
        Overrides the default client authentication to only allow the MCP server's
        confidential client.
        """
        core = self.get_oauthlib_core()
        oauthlib_request = OAuthLibRequest(*core._extract_params(request))
        if not core.server.request_validator.authenticate_client(oauthlib_request):
            return False

        return OAuthAuthorizationServerService.is_mcp_client(oauthlib_request.client)

    @staticmethod
    def get_token_response(token_value=None):
        if token_value is None:
            return JsonResponse(
                {
                    "error": "invalid_request",
                    "error_description": "Token parameter is missing.",
                },
                status=400,
            )

        return JsonResponse(OAuthAuthorizationServerService().introspect(token_value))


class OAuthAuthorizeView(APIView):
    """
    Backs the web consent page. The page forwards the client's authorization
    request as the query string: GET describes it, POST records the decision.
    """

    def get(self, request):
        try:
            consent_request = OAuthAuthorizationServerService().get_consent_request(
                request._request
            )
        except AuthorizationError as error:
            return self._error_response(error)
        return Response(asdict(consent_request))

    def post(self, request):
        allow = request.data.get("allow") is True
        try:
            redirect_url = OAuthAuthorizationServerService().decide(
                request._request, allow
            )
        except AuthorizationError as error:
            return self._error_response(error)
        return Response({"redirect_url": redirect_url})

    @staticmethod
    def _error_response(error):
        if not error.redirect_url:
            return Response(
                {
                    "error": error.error,
                    "error_description": error.description,
                },
                status=400,
            )

        return Response({"redirect_url": error.redirect_url})
