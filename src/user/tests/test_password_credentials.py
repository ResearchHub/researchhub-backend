from unittest.mock import patch

from allauth.account.forms import default_token_generator
from allauth.account.utils import user_pk_to_url_str
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from user.services.auth_token_service import AuthTokenService
from user.views.password_change_view import PasswordChangeThrottle
from utils.test_helpers import generate_password

User = get_user_model()


class PasswordCredentialTestCase(APITestCase):
    def setUp(self):
        self.password = generate_password()
        self.new_password = generate_password()
        self.user = User.objects.create_user(
            username="password-user@researchhub_test.com",
            email="password-user@researchhub_test.com",
            password=self.password,
        )
        self.token = AuthTokenService().issue(self.user)

    def client_for(self, key):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {key}")
        return client

    def probe_status(self, key):
        return self.client_for(key).get("/api/auth/mfa/status/").status_code


class PasswordChangeTests(PasswordCredentialTestCase):
    url = "/api/auth/password-change/"

    def change_password(self, **extra):
        return self.client_for(self.token.key).post(
            self.url,
            {
                "new_password1": self.new_password,
                "new_password2": self.new_password,
                **extra,
            },
            format="json",
        )

    def test_current_password_is_required(self):
        # Act
        response = self.change_password()

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("old_password", response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.password))

    def test_wrong_current_password_changes_nothing(self):
        # Act
        response = self.change_password(old_password=generate_password())

        # Assert
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.password))
        self.assertTrue(Token.objects.filter(key=self.token.key).exists())

    def test_change_replaces_the_token(self):
        # Act
        response = self.change_password(old_password=self.password)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))
        new_key = response.data["key"]
        self.assertNotEqual(new_key, self.token.key)
        self.assertEqual(self.probe_status(self.token.key), 401)
        self.assertEqual(self.probe_status(new_key), 200)

    def test_account_without_usable_password_cannot_set_one_with_a_token(self):
        # Arrange
        self.user.set_unusable_password()
        self.user.save(update_fields=["password"])

        # Act
        response = self.change_password(old_password=self.password)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())

    @patch.object(PasswordChangeThrottle, "rate", "1/hour")
    def test_repeated_attempts_are_throttled(self):
        # Arrange
        self.change_password(old_password=generate_password())

        # Act
        response = self.change_password(old_password=generate_password())

        # Assert
        self.assertEqual(response.status_code, 429)


class PasswordResetConfirmTests(PasswordCredentialTestCase):
    def test_reset_revokes_the_token(self):
        # Arrange
        payload = {
            "uid": user_pk_to_url_str(self.user),
            "token": default_token_generator.make_token(self.user),
            "new_password1": self.new_password,
            "new_password2": self.new_password,
        }

        # Act
        response = self.client.post("/api/auth/confirm/", payload, format="json")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Token.objects.filter(user=self.user).exists())
        self.assertEqual(self.probe_status(self.token.key), 401)

    def test_invalid_reset_link_keeps_the_token(self):
        # Arrange
        payload = {
            "uid": user_pk_to_url_str(self.user),
            "token": "invalid-token",
            "new_password1": self.new_password,
            "new_password2": self.new_password,
        }

        # Act
        response = self.client.post("/api/auth/confirm/", payload, format="json")

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Token.objects.filter(key=self.token.key).exists())
