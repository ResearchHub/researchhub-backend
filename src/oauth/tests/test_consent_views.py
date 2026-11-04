from urllib.parse import parse_qs, urlencode, urlparse

from django.conf import settings
from django.test import override_settings
from oauth2_provider.models import get_application_model, get_grant_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from user.tests.helpers import create_random_default_user

Application = get_application_model()
Grant = get_grant_model()

MCP_RESOURCE = "https://mcp.example.com/v1/mcp"
REDIRECT_URI = "http://127.0.0.1:33418/callback"


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

    def test_requires_sign_in(self):
        # Arrange
        self.client.credentials()

        # Act
        response = self.client.get(self.url, self.params)

        # Assert
        self.assertEqual(response.status_code, 401)
