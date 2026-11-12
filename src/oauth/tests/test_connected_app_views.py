import uuid
from datetime import timedelta

from django.conf import settings
from django.test import override_settings
from django.utils import timezone
from oauth2_provider.models import (
    get_access_token_model,
    get_application_model,
    get_refresh_token_model,
)
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from oauth.models import DelegatedAccessToken
from oauth.services.authorization_server_service import OAuthAuthorizationServerService
from user.tests.helpers import create_random_default_user

AccessToken = get_access_token_model()
Application = get_application_model()
RefreshToken = get_refresh_token_model()

API_RESOURCE = "https://api.example.com"
MCP_RESOURCE = "https://mcp.example.com/v1/mcp"
REDIRECT_URI = "http://127.0.0.1:33418/callback"
READ_SCOPE = [
    {"name": "read", "description": settings.OAUTH2_PROVIDER["SCOPES"]["read"]}
]


@override_settings(OAUTH_ENABLED=True, OAUTH_API_RESOURCE=API_RESOURCE)
class ConnectedAppViewSetTests(APITestCase):
    url = "/api/oauth/connected_apps/"

    def setUp(self):
        self.user = create_random_default_user("oauth_connected_apps")
        token, _ = Token.objects.get_or_create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.application = self._create_application("AIApp1")

    @staticmethod
    def _create_application(name, **fields):
        return Application.objects.create(
            name=name,
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris=REDIRECT_URI,
            **fields,
        )

    def _connect(self, name, user=None, application=None, used_at=None):
        """
        Creates the tokens a client holds after the user authorizes it.
        """
        user = user or self.user
        application = application or self.application
        access_token = AccessToken.objects.create(
            user=user,
            application=application,
            token=f"{name}-access",
            expires=timezone.now() + timedelta(hours=1),
            scope="read",
            resource=[MCP_RESOURCE],
        )
        refresh_token = RefreshToken.objects.create(
            user=user,
            application=application,
            token=f"{name}-refresh",
            access_token=access_token,
            token_family=uuid.uuid4(),
        )
        if used_at:
            RefreshToken.objects.filter(pk=refresh_token.pk).update(created=used_at)
            refresh_token.refresh_from_db()
        return refresh_token

    def test_lists_connected_apps_most_recently_used_first(self):
        # Arrange
        used_at = timezone.now() - timedelta(days=2)
        self._connect("first", used_at=used_at)
        other_app = self._create_application("AIApp2")
        recent = self._connect("second", application=other_app)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            [
                {
                    "id": other_app.id,
                    "name": "AIApp2",
                    "scopes": READ_SCOPE,
                    "last_used_at": recent.created,
                },
                {
                    "id": self.application.id,
                    "name": "AIApp1",
                    "scopes": READ_SCOPE,
                    "last_used_at": used_at,
                },
            ],
        )

    def test_lists_a_client_authorized_twice_once(self):
        # Arrange
        self._connect("older", used_at=timezone.now() - timedelta(days=2))
        newer = self._connect("newer")

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["last_used_at"], newer.created)

    def test_names_a_cimd_client_by_its_host_not_its_claimed_name(self):
        # Arrange
        cimd_app = self._create_application(
            "Claude",
            client_id="https://client.example.com/oauth/metadata.json",
            registration_source=Application.RegistrationSource.CIMD,
        )
        self._connect("cimd", application=cimd_app)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.data[0]["name"], "client.example.com")

    def test_excludes_revoked_and_other_users_authorizations(self):
        # Arrange
        revoked = self._connect("revoked")
        revoked.revoke()
        other_user = create_random_default_user("oauth_other")
        self._connect(
            "other", user=other_user, application=self._create_application("AIApp2")
        )

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.data, [])

    def test_revoke_disconnects_the_client_and_its_exchanged_api_tokens(self):
        # Arrange
        refresh_token = self._connect("app")
        self._connect("app-again")
        api_token = AccessToken.objects.create(
            user=self.user,
            application=self._create_application("MCP"),
            token="app-api",
            expires=timezone.now() + timedelta(minutes=5),
            scope="read",
            resource=[API_RESOURCE],
        )
        DelegatedAccessToken.objects.create(
            access_token=api_token, source_token=refresh_token.access_token
        )
        other_app = self._create_application("AIApp2")
        self._connect("other", application=other_app)

        # Act
        response = self.client.delete(f"{self.url}{self.application.id}/")

        # Assert
        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            RefreshToken.objects.filter(
                application=self.application, revoked__isnull=True
            ).exists()
        )
        self.assertFalse(
            AccessToken.objects.filter(application=self.application).exists()
        )
        self.assertIsNone(OAuthAuthorizationServerService().get_api_token("app-api"))
        self.assertEqual(
            [app["id"] for app in self.client.get(self.url).data], [other_app.id]
        )

    def test_revoke_keeps_other_users_authorizations(self):
        # Arrange
        other_user = create_random_default_user("oauth_other")
        self._connect("other", user=other_user)

        # Act
        response = self.client.delete(f"{self.url}{self.application.id}/")

        # Assert
        self.assertEqual(response.status_code, 204)
        self.assertTrue(
            RefreshToken.objects.filter(user=other_user, revoked__isnull=True).exists()
        )

    def test_requires_sign_in(self):
        # Arrange
        self._connect("app")
        credentials = {
            "none": {},
            "OAuth access token": {"HTTP_AUTHORIZATION": "Bearer app-access"},
        }
        for case, headers in credentials.items():
            self.client.credentials(**headers)
            with self.subTest(case=case):
                # Act
                list_response = self.client.get(self.url)
                revoke_response = self.client.delete(
                    f"{self.url}{self.application.id}/"
                )

                # Assert
                self.assertEqual(list_response.status_code, 401)
                self.assertEqual(revoke_response.status_code, 401)
        self.assertTrue(RefreshToken.objects.filter(revoked__isnull=True).exists())
