from django.utils.translation import gettext_lazy as _
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed

from user.services.auth_token_service import AuthTokenService


class ExpiringTokenAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        service = AuthTokenService()
        token = service.get_active_token(key)
        if token is None:
            raise AuthenticationFailed(_("Invalid or expired token."))
        service.record_use(token)
        return token.user, token
