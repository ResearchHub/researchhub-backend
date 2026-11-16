from datetime import timedelta

from django.test import override_settings
from django.utils import timezone
from oauth2_provider.models import get_access_token_model, get_application_model
from rest_framework.test import APITestCase

from oauth.models import DelegatedAccessToken
from purchase.models import RscExchangeRate
from user.tests.helpers import create_random_authenticated_user

AccessToken = get_access_token_model()
Application = get_application_model()

API_RESOURCE = "https://api.example.com"
MCP_RESOURCE = "https://mcp.example.com/v1/mcp"


@override_settings(
    OAUTH_ENABLED=True,
    OAUTH_MCP_RESOURCE=MCP_RESOURCE,
    OAUTH_API_RESOURCE=API_RESOURCE,
)
class DelegatedTokenAuthenticationTests(APITestCase):
    url = "/api/funder/funding_overview/"

    def setUp(self):
        self.user = create_random_authenticated_user("oauth_api", moderator=True)
        RscExchangeRate.objects.create(
            rate=0.5, real_rate=0.5, price_source="COIN_GECKO", target_currency="USD"
        )
        self.application = Application.objects.create(
            name="AIApp1",
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://127.0.0.1:33418/callback",
        )
        self.mcp_client = Application.objects.create(
            name="MCP",
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_CLIENT_CREDENTIALS,
        )
        self._create_api_token("api-token")

    def _create_token(
        self,
        token,
        resource,
        user=None,
        application=None,
        expires_in=timedelta(hours=1),
    ):
        return AccessToken.objects.create(
            user=user or self.user,
            application=application or self.application,
            token=token,
            expires=timezone.now() + expires_in,
            scope="read",
            resource=resource,
        )

    def _create_api_token(self, token, user=None, expires_in=timedelta(minutes=5)):
        """
        Creates an API token as the token exchange does, with its MCP token.
        """
        mcp_token = self._create_token(f"mcp-{token}", [MCP_RESOURCE], user=user)
        api_token = self._create_token(
            token,
            [API_RESOURCE],
            user=user,
            application=self.mcp_client,
            expires_in=expires_in,
        )
        DelegatedAccessToken.objects.create(
            access_token=api_token, source_token=mcp_token
        )
        return api_token

    def _get(self, token, url=None, **params):
        return self.client.get(
            url or self.url, params, HTTP_AUTHORIZATION=f"Bearer {token}"
        )

    def test_api_token_reads_the_funding_overview(self):
        # Act
        response = self._get("api-token")

        # Assert
        self.assertEqual(response.status_code, 200)

    def test_rejects_tokens_that_are_not_usable_api_tokens(self):
        # Arrange
        self._create_token("other-resource-token", ["https://other.example.com"])
        self._create_token("unbound-token", [])
        self._create_token(
            "unlinked-api-token", [API_RESOURCE], application=self.mcp_client
        )
        self._create_api_token("expired-api-token", expires_in=timedelta(seconds=-1))
        revoked = self._create_api_token("revoked-api-token")
        revoked.delegation.source_token.delete()
        inactive_user = create_random_authenticated_user("oauth_api_inactive")
        inactive_user.is_active = False
        inactive_user.save()
        self._create_api_token("inactive-user-api-token", user=inactive_user)

        cases = {
            "MCP token": "mcp-api-token",
            "other resource": "other-resource-token",
            "no resource": "unbound-token",
            "not from an exchange": "unlinked-api-token",
            "expired": "expired-api-token",
            "MCP token revoked": "revoked-api-token",
            "deactivated user": "inactive-user-api-token",
        }
        for case, token in cases.items():
            with self.subTest(case=case):
                # Act
                response = self._get(token)

                # Assert
                self.assertEqual(response.status_code, 401)

    def test_views_without_opt_in_reject_api_tokens(self):
        # Act
        response = self._get("api-token", url="/api/funder/funding_impact/")

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_api_token_ignores_the_moderator_user_id(self):
        # Act
        response = self._get("api-token", user_id=999999)

        # Assert
        # A moderator's `Token` request with this ID gets a 404
        self.assertEqual(response.status_code, 200)

    @override_settings(OAUTH_ENABLED=False)
    def test_api_tokens_are_rejected_while_oauth_is_disabled(self):
        # Act
        response = self._get("api-token")

        # Assert
        self.assertEqual(response.status_code, 401)
