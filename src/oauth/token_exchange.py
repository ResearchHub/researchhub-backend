import json

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from oauthlib.oauth2 import Server
from oauthlib.oauth2.rfc6749 import errors
from oauthlib.oauth2.rfc6749.grant_types.base import GrantTypeBase

from oauth.services.authorization_server_service import OAuthAuthorizationServerService

TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"
MAX_EXCHANGED_TOKEN_SECONDS = 5 * 60


class OAuthServer(Server):
    """
    oauthlib's server with the token exchange grant added.
    """

    def __init__(self, request_validator, *args, **kwargs):
        super().__init__(request_validator, *args, **kwargs)
        self.grant_types[TOKEN_EXCHANGE_GRANT] = TokenExchangeGrant(request_validator)


class TokenExchangeGrant(GrantTypeBase):
    """
    Exchanges a user's MCP token for a short-lived API token for the same user
    (RFC 8693), so the MCP server never passes the user's token on to the API.
    Only the MCP server's confidential client may use it.
    """

    def create_token_response(self, request, token_handler):
        headers = self._get_default_headers()
        try:
            with transaction.atomic():
                token = self._exchange(request, token_handler)
        except errors.OAuth2Error as error:
            headers.update(error.headers)
            return headers, error.json, error.status_code

        return headers, json.dumps(token), 200

    def _exchange(self, request, token_handler):
        service = OAuthAuthorizationServerService()
        self._authenticate_mcp_client(request)
        source_token = self._validate_subject_token(request, service)
        self._validate_resource(request)
        request.user = source_token.user
        request.scopes = self._validate_scopes(request, source_token)

        token = token_handler.create_token(request, refresh_token=False)
        remaining = (source_token.expires - timezone.now()).total_seconds()
        token["expires_in"] = int(min(MAX_EXCHANGED_TOKEN_SECONDS, remaining))
        token["issued_token_type"] = ACCESS_TOKEN_TYPE
        self.request_validator.save_token(token, request)
        service.record_token_exchange(token["access_token"], source_token)
        return token

    def _authenticate_mcp_client(self, request):
        if not self.request_validator.authenticate_client(request):
            raise errors.InvalidClientError(request=request)

        client = request.client
        if (
            client.client_id != settings.OAUTH_MCP_CLIENT_ID
            or client.client_type != client.CLIENT_CONFIDENTIAL
        ):
            raise errors.UnauthorizedClientError(request=request)

    def _validate_subject_token(self, request, service):
        token_types = (
            getattr(request, "subject_token_type", None),
            getattr(request, "requested_token_type", None) or ACCESS_TOKEN_TYPE,
        )
        if token_types != (ACCESS_TOKEN_TYPE, ACCESS_TOKEN_TYPE):
            raise errors.InvalidRequestError(
                description="Only access tokens can be exchanged.", request=request
            )

        subject_token = getattr(request, "subject_token", None)
        source_token = subject_token and service.get_active_token(
            subject_token, for_update=True
        )
        # Only MCP tokens qualify, so API tokens can't be exchanged again:
        if not source_token or source_token.resource != [settings.OAUTH_MCP_RESOURCE]:
            raise errors.InvalidRequestError(
                description="The subject token is invalid.", request=request
            )

        return source_token

    def _validate_resource(self, request):
        resources = [
            value for key, value in request.decoded_body or [] if key == "resource"
        ]
        if resources != [settings.OAUTH_API_RESOURCE]:
            raise errors.CustomOAuth2Error(
                error="invalid_target",
                description="The requested resource is not supported.",
                request=request,
            )

    def _validate_scopes(self, request, source_token):
        granted = source_token.scope.split()
        requested = request.scopes or granted
        if not set(requested) <= set(granted):
            raise errors.InvalidScopeError(request=request)

        return requested
