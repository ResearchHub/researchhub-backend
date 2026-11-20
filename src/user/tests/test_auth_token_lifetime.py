from datetime import timedelta

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from user.models import AuthTokenActivity
from user.services.auth_token_service import (
    LAST_USED_WRITE_INTERVAL,
    AuthTokenService,
)
from utils.test_helpers import generate_password

User = get_user_model()


class AuthTokenTestCase(APITestCase):
    def setUp(self):
        self.password = generate_password()
        self.user = User.objects.create_user(
            username="token-user@example.com",
            email="token-user@example.com",
            password=self.password,
        )
        self.service = AuthTokenService()
        self.token = self.service.issue(self.user)

    def age_token(self, issued_ago=timedelta(0), last_used_ago=timedelta(0)):
        now = timezone.now()
        AuthTokenActivity.objects.filter(token=self.token).update(
            issued_at=now - issued_ago,
            last_used_at=now - last_used_ago,
        )

    def get_authenticated(self, key):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {key}")
        return client.get("/api/auth/mfa/status/")


class ExpiringTokenAuthenticationTests(AuthTokenTestCase):
    def test_active_token_authenticates(self):
        # Act
        response = self.get_authenticated(self.token.key)

        # Assert
        self.assertEqual(response.status_code, 200)

    def test_idle_token_is_rejected(self):
        # Arrange
        self.age_token(
            issued_ago=settings.AUTH_TOKEN_IDLE_LIFETIME,
            last_used_ago=settings.AUTH_TOKEN_IDLE_LIFETIME,
        )

        # Act
        response = self.get_authenticated(self.token.key)

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_token_past_absolute_lifetime_is_rejected_despite_recent_use(self):
        # Arrange
        self.age_token(issued_ago=settings.AUTH_TOKEN_ABSOLUTE_LIFETIME)

        # Act
        response = self.get_authenticated(self.token.key)

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_use_extends_idle_window_but_not_absolute_lifetime(self):
        # Arrange
        issued_ago = settings.AUTH_TOKEN_IDLE_LIFETIME + timedelta(days=1)
        self.age_token(
            issued_ago=issued_ago,
            last_used_ago=settings.AUTH_TOKEN_IDLE_LIFETIME - timedelta(hours=1),
        )
        issued_at = AuthTokenActivity.objects.get(token=self.token).issued_at

        # Act
        response = self.get_authenticated(self.token.key)

        # Assert
        self.assertEqual(response.status_code, 200)
        activity = AuthTokenActivity.objects.get(token=self.token)
        self.assertEqual(activity.issued_at, issued_at)
        self.assertLess(timezone.now() - activity.last_used_at, timedelta(minutes=1))

    def test_recent_use_does_not_write_last_used(self):
        # Arrange
        self.age_token(last_used_ago=LAST_USED_WRITE_INTERVAL - timedelta(minutes=5))
        last_used_at = AuthTokenActivity.objects.get(token=self.token).last_used_at

        # Act
        self.get_authenticated(self.token.key)

        # Assert
        activity = AuthTokenActivity.objects.get(token=self.token)
        self.assertEqual(activity.last_used_at, last_used_at)

    def test_untracked_token_starts_tracking_from_its_creation_time(self):
        # Arrange
        AuthTokenActivity.objects.filter(token=self.token).delete()
        self.token.refresh_from_db()

        # Act
        response = self.get_authenticated(self.token.key)

        # Assert
        self.assertEqual(response.status_code, 200)
        activity = AuthTokenActivity.objects.get(token=self.token)
        self.assertEqual(activity.issued_at, self.token.created)

    def test_old_untracked_token_is_rejected(self):
        # Arrange
        AuthTokenActivity.objects.filter(token=self.token).delete()
        Token.objects.filter(pk=self.token.pk).update(
            created=timezone.now() - settings.AUTH_TOKEN_IDLE_LIFETIME
        )

        # Act
        response = self.get_authenticated(self.token.key)

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_inactive_user_is_rejected(self):
        # Arrange
        User.objects.filter(pk=self.user.pk).update(is_active=False)

        # Act
        response = self.get_authenticated(self.token.key)

        # Assert
        self.assertEqual(response.status_code, 401)

    @override_settings(AUTH_TOKEN_IDLE_LIFETIME=timedelta(hours=2))
    def test_idle_lifetime_comes_from_settings(self):
        # Arrange
        self.age_token(last_used_ago=timedelta(hours=3))

        # Act
        response = self.get_authenticated(self.token.key)

        # Assert
        self.assertEqual(response.status_code, 401)


class AuthTokenIssueTests(AuthTokenTestCase):
    def login(self):
        EmailAddress.objects.update_or_create(
            user=self.user,
            email=self.user.email,
            defaults={"verified": True, "primary": True},
        )
        return self.client.post(
            "/api/auth/login/",
            {"email": self.user.email, "password": self.password},
            format="json",
        )

    def test_login_reuses_token_with_enough_life_left(self):
        # Act
        response = self.login()

        # Assert
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["key"], self.token.key)

    def test_login_keeps_absolute_clock_of_reused_token(self):
        # Arrange
        self.age_token(issued_ago=timedelta(days=1))
        issued_at = AuthTokenActivity.objects.get(token=self.token).issued_at

        # Act
        self.login()

        # Assert
        activity = AuthTokenActivity.objects.get(token=self.token)
        self.assertEqual(activity.issued_at, issued_at)

    def test_login_replaces_expired_token(self):
        # Arrange
        self.age_token(issued_ago=settings.AUTH_TOKEN_ABSOLUTE_LIFETIME)

        # Act
        response = self.login()

        # Assert
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotEqual(response.data["key"], self.token.key)
        self.assertFalse(Token.objects.filter(key=self.token.key).exists())
        self.assertEqual(self.get_authenticated(response.data["key"]).status_code, 200)

    def test_login_replaces_token_with_less_than_an_idle_window_left(self):
        # Arrange
        self.age_token(
            issued_ago=settings.AUTH_TOKEN_ABSOLUTE_LIFETIME
            - settings.AUTH_TOKEN_IDLE_LIFETIME
            + timedelta(hours=1)
        )

        # Act
        response = self.login()

        # Assert
        self.assertNotEqual(response.data["key"], self.token.key)

    def test_issue_tracks_new_token(self):
        # Arrange
        self.token.delete()

        # Act
        token = self.service.issue(self.user)

        # Assert
        self.assertTrue(AuthTokenActivity.objects.filter(token=token).exists())

    def test_deleting_token_removes_its_activity(self):
        # Act
        self.service.revoke(self.user)

        # Assert
        self.assertFalse(AuthTokenActivity.objects.exists())
