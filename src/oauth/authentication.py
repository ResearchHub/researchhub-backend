from django.conf import settings
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from oauth.services.authorization_server_service import OAuthAuthorizationServerService


class DelegatedTokenAuthentication(BaseAuthentication):
    """
    Authenticates the API tokens the MCP server gets through token exchange, sent
    as `Authorization: Bearer <token>`.
    Enabled by including this class in the view's `authentication_classes`.
    """

    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not settings.OAUTH_ENABLED or not auth or auth[0].lower() != b"bearer":
            return None
        if len(auth) != 2:
            raise AuthenticationFailed("Invalid bearer token header.")

        try:
            token_value = auth[1].decode()
        except UnicodeError:
            raise AuthenticationFailed("Invalid bearer token header.") from None

        token = OAuthAuthorizationServerService().get_api_token(token_value)
        if token is None:
            raise AuthenticationFailed("Invalid or expired token.")

        return token.user, token

    def authenticate_header(self, request):
        return "Bearer"
