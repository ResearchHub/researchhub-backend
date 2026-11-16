import base64
import hashlib
from datetime import timedelta
from urllib.parse import urlencode

from django.test import TestCase, override_settings
from django.utils import timezone
from oauth2_provider.models import get_access_token_model, get_application_model

from user.tests.helpers import create_random_default_user

AccessToken = get_access_token_model()
Application = get_application_model()

API_RESOURCE = "https://api.example.com"
MCP_RESOURCE = "https://mcp.example.com/v1/mcp"
TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"


def basic_auth(client_id, secret):
    credentials = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    return f"Basic {credentials}"


@override_settings(
    OAUTH_ENABLED=True,
    OAUTH_MCP_RESOURCE=MCP_RESOURCE,
    OAUTH_API_RESOURCE=API_RESOURCE,
    OAUTH_MCP_CLIENT_ID="mcp-client",
)
class TokenExchangeTests(TestCase):
    url = "/oauth/token/"

    def setUp(self):
        self.user = create_random_default_user("oauth_exchange")
        self.mcp_client = Application.objects.create(
            client_id="mcp-client",
            name="MCP",
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_CLIENT_CREDENTIALS,
            client_secret="mcp-secret",
        )
        self.application = Application.objects.create(
            name="AIApp1",
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://127.0.0.1:33418/callback",
        )
        self.mcp_token = self._create_token("mcp-token")
        self.params = {
            "grant_type": TOKEN_EXCHANGE_GRANT,
            "subject_token": "mcp-token",
            "subject_token_type": ACCESS_TOKEN_TYPE,
            "requested_token_type": ACCESS_TOKEN_TYPE,
            "resource": API_RESOURCE,
            "scope": "read",
        }

    def _create_token(
        self, token, user=None, resource=MCP_RESOURCE, expires_in=timedelta(hours=1)
    ):
        return AccessToken.objects.create(
            user=user or self.user,
            application=self.application,
            token=token,
            expires=timezone.now() + expires_in,
            scope="read",
            resource=[resource],
        )

    def _exchange(self, auth=None, **params):
        return self.client.post(
            self.url,
            urlencode({**self.params, **params}, doseq=True),
            content_type="application/x-www-form-urlencoded",
            HTTP_AUTHORIZATION=auth or basic_auth("mcp-client", "mcp-secret"),
        )

    def test_exchanges_an_mcp_token_for_an_api_token_of_the_same_user(self):
        # Act
        response = self._exchange()

        # Assert
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["token_type"], "Bearer")
        self.assertEqual(body["issued_token_type"], ACCESS_TOKEN_TYPE)
        self.assertEqual(body["scope"], "read")
        self.assertEqual(body["expires_in"], 300)
        self.assertNotIn("refresh_token", body)
        checksum = hashlib.sha256(body["access_token"].encode()).hexdigest()
        api_token = AccessToken.objects.get(token_checksum=checksum)
        self.assertEqual(api_token.user, self.user)
        self.assertEqual(api_token.application, self.mcp_client)
        self.assertEqual(api_token.resource, [API_RESOURCE])
        self.assertEqual(api_token.delegation.source_token, self.mcp_token)

    def test_api_token_never_outlives_the_mcp_token(self):
        # Arrange
        self.mcp_token.expires = timezone.now() + timedelta(seconds=60)
        self.mcp_token.save()

        # Act
        response = self._exchange()

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(response.json()["expires_in"], 60)

    def test_rejects_clients_other_than_the_mcp_client(self):
        # Arrange
        Application.objects.create(
            client_id="other-client",
            name="Other",
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_CLIENT_CREDENTIALS,
            client_secret="other-secret",
        )

        cases = {
            "wrong secret": (basic_auth("mcp-client", "wrong"), 401, "invalid_client"),
            "other client": (
                basic_auth("other-client", "other-secret"),
                400,
                "unauthorized_client",
            ),
        }
        for case, (auth, status, error) in cases.items():
            with self.subTest(case=case):
                # Act
                response = self._exchange(auth=auth)

                # Assert
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"], error)

    def test_rejects_subject_tokens_that_are_not_live_mcp_tokens(self):
        # Arrange
        self._create_token("expired-token", expires_in=timedelta(seconds=-1))
        self._create_token("api-token", resource=API_RESOURCE)
        inactive_user = create_random_default_user("oauth_exchange_inactive")
        inactive_user.is_active = False
        inactive_user.save()
        self._create_token("inactive-user-token", user=inactive_user)

        cases = {
            "unknown": {"subject_token": "unknown-token"},
            "expired": {"subject_token": "expired-token"},
            "API token": {"subject_token": "api-token"},
            "deactivated user": {"subject_token": "inactive-user-token"},
            "refresh token type": {
                "subject_token_type": "urn:ietf:params:oauth:token-type:refresh_token"
            },
        }
        for case, params in cases.items():
            with self.subTest(case=case):
                # Act
                response = self._exchange(**params)

                # Assert
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"], "invalid_request")

    def test_rejects_resources_other_than_the_api(self):
        cases = {
            "MCP resource": {"resource": MCP_RESOURCE},
            "no resource": {"resource": []},
        }
        for case, params in cases.items():
            with self.subTest(case=case):
                # Act
                response = self._exchange(**params)

                # Assert
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"], "invalid_target")

    def test_rejects_scopes_beyond_the_mcp_token(self):
        # Act
        response = self._exchange(scope="read write")

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_scope")
        self.assertFalse(
            AccessToken.objects.filter(application=self.mcp_client).exists()
        )
