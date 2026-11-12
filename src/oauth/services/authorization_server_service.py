import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction
from oauth2_provider.exceptions import FatalClientError, OAuthToolkitError
from oauth2_provider.models import (
    get_access_token_model,
    get_application_model,
    get_grant_model,
    get_refresh_token_model,
)
from oauth2_provider.oauth2_backends import _add_iss_to_redirect, get_oauthlib_core
from oauth2_provider.scopes import get_scopes_backend
from oauth2_provider.settings import oauth2_settings
from oauthlib.oauth2 import AccessDeniedError
from oauthlib.oauth2.rfc6749.errors import CustomOAuth2Error, InvalidRedirectURIError

from oauth.models import DelegatedAccessToken

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


@dataclass(frozen=True)
class ConnectedApp:
    id: int
    name: str
    scopes: list[dict]
    last_used_at: datetime


class OAuthAuthorizationServerService:
    """
    Handles OAuth 2.0 authorization requests, validates them, facilitates the consent
    process for the user, and introspects and revokes tokens.
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
        return ConsentRequest(
            client_name=self._client_name(application),
            redirect_host=redirect_host,
            loopback_redirect=redirect_host in LOOPBACK_HOSTS,
            scopes=self._describe_scopes(scopes),
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

    def introspect(self, token_value: str) -> dict:
        """
        Returns the introspection response for an access token.
        """
        token = self.get_active_token(token_value)
        if token is None:
            return {"active": False}

        response = {
            "active": True,
            "sub": str(token.user.id),
            "client_id": token.application.client_id,
            "scope": token.scope,
            "exp": int(token.expires.timestamp()),
        }
        if token.resource:
            response["aud"] = token.resource
        return response

    def get_active_token(self, token_value: str, for_update=False):
        """
        Returns the access token if it is unexpired and its user is active,
        and `None` otherwise.
        With `for_update`, the token stays locked until the transaction ends,
        so it can't be revoked in the meantime.
        """
        tokens = get_access_token_model().objects.select_related("user", "application")
        if for_update:
            tokens = tokens.select_for_update(of=("self",))
        checksum = hashlib.sha256(token_value.encode()).hexdigest()
        token = tokens.filter(token_checksum=checksum).first()
        if token is None or not token.is_valid():
            return None
        if token.user is None or not token.user.is_active:
            return None

        return token

    def get_api_token(self, token_value: str):
        """
        Returns the API token from a token exchange if it is active and still
        linked to the MCP token it was exchanged for, and `None` otherwise.
        """
        token = self.get_active_token(token_value)
        if token is None or token.resource != [settings.OAUTH_API_RESOURCE]:
            return None
        # Revoking the MCP token deletes the link:
        if not DelegatedAccessToken.objects.filter(access_token=token).exists():
            return None

        return token

    def list_connected_apps(self, user) -> list[ConnectedApp]:
        """
        Returns the clients the user has authorized and not revoked, most recently
        used first. `last_used_at` is when the client last obtained a token.
        """
        refresh_tokens = (
            get_refresh_token_model()
            .objects.filter(user=user, revoked__isnull=True, access_token__isnull=False)
            .select_related("application", "access_token")
            .order_by("-created")
        )
        # A client the user authorized more than once holds a token for each:
        last_used = {}
        scopes = defaultdict(set)
        for refresh_token in refresh_tokens:
            application = refresh_token.application
            last_used.setdefault(application, refresh_token.created)
            scopes[application].update(refresh_token.access_token.scope.split())

        return [
            ConnectedApp(
                id=application.id,
                name=self._client_name(application),
                scopes=self._describe_scopes(sorted(scopes[application])),
                last_used_at=last_used_at,
            )
            for application, last_used_at in last_used.items()
        ]

    def revoke_user_tokens(self, user, application_id=None) -> None:
        """
        Revokes a user's tokens and authorization codes, for all clients or only
        the given one. API tokens exchanged for a revoked token stop working too,
        because deleting it deletes their delegation links.
        """
        filters = {"user": user}
        if application_id is not None:
            filters["application_id"] = application_id

        with transaction.atomic():
            refresh_tokens = get_refresh_token_model().objects.filter(
                revoked__isnull=True, **filters
            )
            for refresh_token in refresh_tokens:
                refresh_token.revoke()
            get_access_token_model().objects.filter(**filters).delete()
            get_grant_model().objects.filter(**filters).delete()

    @staticmethod
    def is_mcp_client(application) -> bool:
        """
        Returns whether the application is the MCP server's confidential client.
        """
        return (
            application.client_id == settings.OAUTH_MCP_CLIENT_ID
            and application.client_type == application.CLIENT_CONFIDENTIAL
        )

    def record_token_exchange(self, token_value: str, source_token):
        """
        Links an access token issued by a token exchange to the token it was
        exchanged for.
        """
        checksum = hashlib.sha256(token_value.encode()).hexdigest()
        access_token = get_access_token_model().objects.get(token_checksum=checksum)
        DelegatedAccessToken.objects.create(
            access_token=access_token, source_token=source_token
        )

    @staticmethod
    def _client_name(application):
        # Use the hostname from the client_id URL as the client name for CIMD clients.
        # This is because the client name can be easily spoofed.
        if application.registration_source == application.RegistrationSource.CIMD:
            return urlparse(application.client_id).hostname

        return application.name

    @staticmethod
    def _describe_scopes(scopes):
        all_scopes = get_scopes_backend().get_all_scopes()
        return [{"name": scope, "description": all_scopes[scope]} for scope in scopes]

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
