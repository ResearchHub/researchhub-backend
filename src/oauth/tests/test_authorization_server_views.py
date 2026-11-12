import base64
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlparse

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone
from oauth2_provider.cimd import SafeMetadataFetcher
from oauth2_provider.models import (
    get_access_token_model,
    get_application_model,
    get_grant_model,
)
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from user.tests.helpers import create_random_default_user

AccessToken = get_access_token_model()
Application = get_application_model()
Grant = get_grant_model()

MCP_RESOURCE = "https://mcp.example.com/v1/mcp"
REDIRECT_URI = "http://127.0.0.1:33418/callback"


class OAuthEndpointTests(TestCase):
    @override_settings(OAUTH_ENABLED=False)
    def test_endpoints_are_not_found_while_oauth_is_disabled(self):
        urls = [
            "/.well-known/oauth-authorization-server",
            "/oauth/token/",
            "/oauth/revoke/",
            "/oauth/introspect/",
            "/api/oauth/authorize/",
            "/api/oauth/connected_apps/",
            "/api/oauth/connected_apps/1/",
        ]
        for url in urls:
            with self.subTest(url=url):
                # Act
                response = self.client.get(url)

                # Assert
                self.assertEqual(response.status_code, 404)


class AuthorizationServerMetadataViewTests(TestCase):
    url = "/.well-known/oauth-authorization-server"

    @override_settings(OAUTH_ENABLED=True, BASE_FRONTEND_URL="https://www.example.com")
    def test_authorization_endpoint_is_the_web_consent_page(self):
        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["authorization_endpoint"],
            "https://www.example.com/oauth/authorize",
        )

    @override_settings(
        OAUTH_ENABLED=True,
        OAUTH2_PROVIDER={
            **settings.OAUTH2_PROVIDER,
            "OIDC_ISS_ENDPOINT": "https://api.example.com",
        },
    )
    def test_metadata_lists_token_and_revocation_but_not_introspection(self):
        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, 200)
        metadata = response.json()
        self.assertEqual(
            metadata["token_endpoint"], "https://api.example.com/oauth/token/"
        )
        self.assertEqual(
            metadata["revocation_endpoint"], "https://api.example.com/oauth/revoke/"
        )
        self.assertNotIn("introspection_endpoint", metadata)


@override_settings(OAUTH_ENABLED=True, OAUTH_MCP_RESOURCE=MCP_RESOURCE)
class OAuthAuthorizeViewTests(APITestCase):
    url = "/api/oauth/authorize/"

    def setUp(self):
        self.user = create_random_default_user("oauth_consent")
        token, _ = Token.objects.get_or_create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.application = Application.objects.create(
            name="AIApp1",
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris=REDIRECT_URI,
        )
        self.params = {
            "response_type": "code",
            "client_id": self.application.client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": "read",
            "state": "client-state",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
            "resource": MCP_RESOURCE,
        }

    def _post(self, allow):
        url = f"{self.url}?{urlencode(self.params)}"
        return self.client.post(url, {"allow": allow}, format="json")

    @staticmethod
    def _redirect_query(response):
        return parse_qs(urlparse(response.data["redirect_url"]).query)

    def test_get_describes_the_authorization_request(self):
        # Act
        response = self.client.get(self.url, self.params)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "client_name": "AIApp1",
                "redirect_host": "127.0.0.1",
                "loopback_redirect": True,
                "scopes": [
                    {
                        "name": "read",
                        "description": settings.OAUTH2_PROVIDER["SCOPES"]["read"],
                    }
                ],
            },
        )

    def test_get_names_a_cimd_client_by_its_host_not_its_claimed_name(self):
        # Arrange
        client_id = "https://client.example.com/oauth/metadata.json"
        document = {
            "client_id": client_id,
            "client_name": "Claude",
            "redirect_uris": ["https://client.example.com/callback"],
            "token_endpoint_auth_method": "none",
        }
        params = {
            **self.params,
            "client_id": client_id,
            "redirect_uri": "https://client.example.com/callback",
        }

        # Act
        with patch.object(SafeMetadataFetcher, "fetch", return_value=(document, 300)):
            response = self.client.get(self.url, params)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["client_name"], "client.example.com")

    def test_get_accepts_a_cimd_client_that_lists_unsupported_grant_types(self):
        # Arrange
        client_id = "https://client.example.com/oauth/metadata.json"
        # Claude's document lists the JWT bearer grant as well
        document = {
            "client_id": client_id,
            "redirect_uris": ["https://client.example.com/callback"],
            "grant_types": [
                "authorization_code",
                "refresh_token",
                "urn:ietf:params:oauth:grant-type:jwt-bearer",
            ],
            "token_endpoint_auth_method": "none",
        }
        params = {
            **self.params,
            "client_id": client_id,
            "redirect_uri": "https://client.example.com/callback",
        }

        # Act
        with patch.object(SafeMetadataFetcher, "fetch", return_value=(document, 300)):
            response = self.client.get(self.url, params)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["client_name"], "client.example.com")

    def test_get_rejects_a_cimd_client_that_lists_a_non_string_grant_type(self):
        # Arrange
        client_id = "https://client.example.com/oauth/metadata.json"
        document = {
            "client_id": client_id,
            "redirect_uris": ["https://client.example.com/callback"],
            "grant_types": ["authorization_code", 42],
            "token_endpoint_auth_method": "none",
        }
        params = {
            **self.params,
            "client_id": client_id,
            "redirect_uri": "https://client.example.com/callback",
        }

        # Act
        with patch.object(SafeMetadataFetcher, "fetch", return_value=(document, 300)):
            response = self.client.get(self.url, params)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("redirect_url", response.data)
        self.assertFalse(Application.objects.filter(client_id=client_id).exists())

    def test_get_does_not_redirect_for_an_invalid_client_or_redirect_uri(self):
        cases = {
            "unknown client": {"client_id": "unknown"},
            "unregistered redirect URI": {"redirect_uri": "https://evil.example.com"},
        }
        for case, params in cases.items():
            with self.subTest(case=case):
                # Act
                response = self.client.get(self.url, {**self.params, **params})

                # Assert
                self.assertEqual(response.status_code, 400)
                self.assertNotIn("redirect_url", response.data)

    def test_get_redirects_an_unsupported_resource_with_state_and_issuer(self):
        cases = {
            "other resource": {"resource": "https://api.example.com/"},
            "missing resource": {"resource": []},
        }
        for case, params in cases.items():
            with self.subTest(case=case):
                # Act
                response = self.client.get(self.url, {**self.params, **params})

                # Assert
                self.assertEqual(response.status_code, 200)
                query = self._redirect_query(response)
                self.assertEqual(query["error"], ["invalid_target"])
                self.assertEqual(query["state"], ["client-state"])
                self.assertEqual(query["iss"], [settings.OAUTH_ISSUER])

    def test_post_approval_redirects_with_a_code_bound_to_the_mcp_resource(self):
        # Act
        response = self._post(allow=True)

        # Assert
        self.assertEqual(response.status_code, 200)
        query = self._redirect_query(response)
        self.assertEqual(query["state"], ["client-state"])
        self.assertEqual(query["iss"], [settings.OAUTH_ISSUER])
        grant = Grant.objects.get(code=query["code"][0])
        self.assertEqual(grant.user, self.user)
        self.assertEqual(grant.resource, [MCP_RESOURCE])

    def test_post_denial_redirects_with_access_denied(self):
        # Act
        response = self._post(allow=False)

        # Assert
        self.assertEqual(response.status_code, 200)
        query = self._redirect_query(response)
        self.assertEqual(query["error"], ["access_denied"])
        self.assertEqual(query["state"], ["client-state"])
        self.assertEqual(query["iss"], [settings.OAUTH_ISSUER])
        self.assertFalse(Grant.objects.exists())

    def test_post_denial_replaces_an_issuer_in_the_redirect_uri(self):
        # Arrange
        redirect_uri = f"{REDIRECT_URI}?iss=https://attacker.example.com"
        self.application.redirect_uris = redirect_uri
        self.application.save()
        self.params["redirect_uri"] = redirect_uri

        # Act
        response = self._post(allow=False)

        # Assert
        query = self._redirect_query(response)
        self.assertEqual(query["error"], ["access_denied"])
        self.assertEqual(query["iss"], [settings.OAUTH_ISSUER])

    def test_post_rejects_a_non_loopback_http_redirect_uri(self):
        # Arrange
        redirect_uri = "http://client.example.com/callback"
        self.application.redirect_uris = redirect_uri
        self.application.save()
        self.params["redirect_uri"] = redirect_uri

        # Act
        response = self._post(allow=True)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("redirect_url", response.data)
        self.assertFalse(Grant.objects.exists())

    def test_get_does_not_redirect_an_error_to_a_non_loopback_http_redirect_uri(self):
        # Arrange
        redirect_uri = "http://client.example.com/callback"
        self.application.redirect_uris = redirect_uri
        self.application.save()
        params = {**self.params, "redirect_uri": redirect_uri, "scope": "unknown"}

        # Act
        response = self.client.get(self.url, params)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("redirect_url", response.data)

    def test_requires_sign_in(self):
        # Arrange
        self.client.credentials()

        # Act
        response = self.client.get(self.url, self.params)

        # Assert
        self.assertEqual(response.status_code, 401)


@override_settings(OAUTH_ENABLED=True, OAUTH_MCP_CLIENT_ID="mcp-client")
class IntrospectionViewTests(TestCase):
    url = "/oauth/introspect/"

    def setUp(self):
        self.user = create_random_default_user("oauth_introspection")
        self.mcp_client = Application.objects.create(
            client_id="mcp-client",
            name="MCP",
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_CLIENT_CREDENTIALS,
            client_secret="mcp-secret",
        )
        self.client_auth = self._basic_auth("mcp-client", "mcp-secret")
        self.application = Application.objects.create(
            name="AIApp1",
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris=REDIRECT_URI,
        )

    def _create_token(self, token, user=None, expires_in=timedelta(hours=1)):
        return AccessToken.objects.create(
            user=user or self.user,
            application=self.application,
            token=token,
            expires=timezone.now() + expires_in,
            scope="read",
            resource=[MCP_RESOURCE],
        )

    @staticmethod
    def _basic_auth(client_id, secret):
        credentials = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
        return f"Basic {credentials}"

    def _introspect(self, token, **headers):
        return self.client.post(self.url, {"token": token}, **headers)

    def test_active_token_describes_user_client_scope_and_audience(self):
        # Arrange
        access_token = self._create_token("active-token")

        # Act
        response = self._introspect("active-token", HTTP_AUTHORIZATION=self.client_auth)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "active": True,
                "sub": str(self.user.id),
                "client_id": self.application.client_id,
                "scope": "read",
                "exp": int(access_token.expires.timestamp()),
                "aud": [MCP_RESOURCE],
            },
        )

    def test_token_is_inactive(self):
        # Arrange
        self._create_token("expired-token", expires_in=timedelta(seconds=-1))
        inactive_user = create_random_default_user("oauth_inactive")
        inactive_user.is_active = False
        inactive_user.save()
        self._create_token("inactive-user-token", user=inactive_user)

        cases = {
            "expired": "expired-token",
            "deactivated user": "inactive-user-token",
            "unknown": "unknown-token",
        }
        for case, token in cases.items():
            with self.subTest(case=case):
                # Act
                response = self._introspect(token, HTTP_AUTHORIZATION=self.client_auth)

                # Assert
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"active": False})

    def test_rejects_callers_other_than_the_mcp_client(self):
        # Arrange
        self._create_token("active-token")
        Application.objects.create(
            client_id="other-client",
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_CLIENT_CREDENTIALS,
            client_secret="other-secret",
        )
        Application.objects.create(
            client_id="public-client",
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris=REDIRECT_URI,
            client_secret="public-secret",
        )

        cases = {
            "no credentials": {},
            "access token": {"HTTP_AUTHORIZATION": "Bearer active-token"},
            "other confidential client": {
                "HTTP_AUTHORIZATION": self._basic_auth("other-client", "other-secret")
            },
            "public client with its secret": {
                "HTTP_AUTHORIZATION": self._basic_auth("public-client", "public-secret")
            },
        }
        for case, headers in cases.items():
            with self.subTest(case=case):
                # Act
                response = self._introspect("active-token", **headers)

                # Assert
                self.assertEqual(response.status_code, 403)

    def test_get_is_not_allowed(self):
        # Arrange
        self._create_token("active-token")

        # Act
        response = self.client.get(
            self.url,
            {"token": "active-token"},
            HTTP_AUTHORIZATION=self.client_auth,
        )

        # Assert
        self.assertEqual(response.status_code, 405)
