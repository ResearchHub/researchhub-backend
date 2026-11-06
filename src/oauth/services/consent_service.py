from dataclasses import dataclass
from urllib.parse import urlparse

from django.conf import settings
from oauth2_provider.exceptions import FatalClientError, OAuthToolkitError
from oauth2_provider.models import get_application_model
from oauth2_provider.oauth2_backends import _add_iss_to_redirect, get_oauthlib_core
from oauth2_provider.scopes import get_scopes_backend
from oauth2_provider.settings import oauth2_settings
from oauthlib.oauth2 import AccessDeniedError
from oauthlib.oauth2.rfc6749.errors import CustomOAuth2Error, InvalidRedirectURIError

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class AuthorizationError(Exception):
    """
    Thrown when an authorization request is refused.
    """

    def __init__(self, oauthlib_error, redirect_url=None):
        super().__init__(oauthlib_error.description)
        self.error = oauthlib_error.error
        self.description = oauthlib_error.description
        self.redirect_url = redirect_url


@dataclass(frozen=True)
class ConsentRequest:
    client_name: str
    redirect_host: str
    loopback_redirect: bool
    scopes: list[dict]


class OAuthConsentService:
    """
    Validates OAuth authorization requests for the consent page and turns the
    signed-in user's decision into the redirect back to the client.
    """

    def __init__(self, oauthlib_core=None):
        self.core = oauthlib_core or get_oauthlib_core()

    def get_consent_request(self, request) -> ConsentRequest:
        """
        Returns a `ConsentRequest` object containing details about the authorization
        request.
        """
        scopes, credentials = self._validate(request)
        application = get_application_model().objects.get(
            client_id=credentials["client_id"]
        )
        redirect_host = urlparse(credentials["redirect_uri"]).hostname
        all_scopes = get_scopes_backend().get_all_scopes()
        return ConsentRequest(
            client_name=application.name,
            redirect_host=redirect_host,
            loopback_redirect=redirect_host in LOOPBACK_HOSTS,
            scopes=[{"name": s, "description": all_scopes[s]} for s in scopes],
        )

    def decide(self, request, allow: bool) -> str:
        """
        Returns the URL that sends the user back to the client: with an
        authorization code when allowed, otherwise with `access_denied`.
        """
        scopes, credentials = self._validate(request)
        if not allow:
            error = AccessDeniedError(request=credentials["request"])
            return self._error_redirect(request, error)

        try:
            uri, _, _, _ = self.core.create_authorization_response(
                request, scopes, credentials, allow=True
            )
        except OAuthToolkitError as error:
            raise self._authorization_error(request, error) from error
        return uri

    def _validate(self, request):
        try:
            scopes, credentials = self.core.validate_authorization_request(request)
        except OAuthToolkitError as error:
            raise self._authorization_error(request, error) from error

        if not self._is_secure_redirect_uri(credentials["redirect_uri"]):
            error = InvalidRedirectURIError(
                description="Redirect URIs must use https unless they are loopback.",
                request=credentials["request"],
            )
            raise AuthorizationError(error)

        # Clients may only request the MCP server, so every token is bound to that
        # audience:
        resources = request.GET.getlist("resource")
        if resources != [settings.OAUTH_MCP_RESOURCE]:
            error = CustomOAuth2Error(
                error="invalid_target",
                description="The requested resource is not supported.",
                request=credentials["request"],
            )
            raise AuthorizationError(error, self._error_redirect(request, error))
        credentials["resource"] = resources
        return scopes, credentials

    def _authorization_error(self, request, error):
        oauthlib_error = error.oauthlib_error
        redirect_uri = oauthlib_error.redirect_uri
        if (
            isinstance(error, FatalClientError)
            or not redirect_uri
            or not self._is_secure_redirect_uri(redirect_uri)
        ):
            return AuthorizationError(oauthlib_error)
        return AuthorizationError(
            oauthlib_error, self._error_redirect(request, oauthlib_error)
        )

    def _error_redirect(self, request, oauthlib_error):
        # DOT adds `iss` only to successful redirects, so reuse its helper here to
        # replace any `iss` already in the redirect URI the same way
        uri = oauthlib_error.in_uri(oauthlib_error.redirect_uri)
        issuer = oauth2_settings.oauth2_authorization_server_issuer(request)
        return _add_iss_to_redirect(uri, issuer)

    @staticmethod
    def _is_secure_redirect_uri(redirect_uri):
        # Only loopback hosts may use plain http for the redirect URI.
        uri = urlparse(redirect_uri)
        return uri.scheme != "http" or uri.hostname in LOOPBACK_HOSTS
