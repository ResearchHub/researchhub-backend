import time
from unittest.mock import patch

import pyotp
from allauth.account.models import EmailAddress
from dj_rest_auth.mfa.totp import TOTP, generate_totp_secret
from dj_rest_auth.mfa.utils import is_mfa_enabled
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from user.views.mfa_views import MFAChangeThrottle
from utils.test_helpers import generate_password

User = get_user_model()


class MFAFlowTests(APITestCase):
    """
    Tests for the MFA authentication flow.
    """

    def register_verified_user(self, email, password):
        response = self.client.post(
            "/api/auth/register/",
            {
                "email": email,
                "password1": password,
                "password2": password,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        user = User.objects.get(email=email)
        email_address = EmailAddress.objects.get(user=user, email=email)
        email_address.verified = True
        email_address.set_as_primary(conditional=True)
        email_address.save()
        return user

    def login(self, email, password):
        return self.client.post(
            "/api/auth/login/",
            {"email": email, "password": password},
            format="json",
        )

    def authenticated_client(self, token):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        return client

    def enable_mfa(self, email, password):
        login_response = self.login(email, password)
        self.assertEqual(login_response.status_code, 200)
        token = login_response.data["key"]

        authed_client = self.authenticated_client(token)
        init_response = authed_client.get("/api/auth/mfa/totp/activate/", format="json")
        self.assertEqual(init_response.status_code, 200)

        secret = init_response.data["secret"]
        activation_token = init_response.data["activation_token"]
        activate_response = authed_client.post(
            "/api/auth/mfa/totp/activate/",
            {
                "activation_token": activation_token,
                "code": pyotp.TOTP(secret).now(),
                "password": password,
            },
            format="json",
        )
        self.assertEqual(activate_response.status_code, 200)
        self.assertIn("recovery_codes", activate_response.data)
        return secret

    def test_login_without_mfa_returns_standard_token_response(self):
        # Arrange
        email = "simple-login@researchhub.com"
        password = generate_password()
        self.register_verified_user(email, password)

        # Act
        response = self.login(email, password)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertIn("key", response.data)
        self.assertNotIn("mfa_required", response.data)
        self.assertNotIn("ephemeral_token", response.data)

    def test_login_with_mfa_returns_ephemeral_token_and_verify_returns_key(self):
        # Arrange
        email = "mfa-login@researchhub.com"
        password = generate_password()
        self.register_verified_user(email, password)
        secret = self.enable_mfa(email, password)

        # Act
        response = self.login(email, password)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["mfa_required"])
        self.assertIn("ephemeral_token", response.data)
        self.assertNotIn("key", response.data)

        # Act
        verify_response = self.client.post(
            "/api/auth/mfa/verify/",
            {
                "ephemeral_token": response.data["ephemeral_token"],
                "code": pyotp.TOTP(secret).now(),
            },
            format="json",
        )

        # Verify
        self.assertEqual(verify_response.status_code, 200)
        self.assertIn("key", verify_response.data)


class MFAChangeConfirmationTests(APITestCase):
    def setUp(self):
        self.password = generate_password()
        self.user = User.objects.create_user(
            username="mfa-change@researchhub_test.com",
            email="mfa-change@researchhub_test.com",
            password=self.password,
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.user).key}"
        )

    def start_activation(self, prefix=""):
        response = self.client.get(f"{prefix}/api/auth/mfa/totp/activate/")
        self.assertEqual(response.status_code, 200)
        return response.data["secret"], response.data["activation_token"]

    def activate(self, prefix="", **extra):
        secret, activation_token = self.start_activation(prefix)
        response = self.client.post(
            f"{prefix}/api/auth/mfa/totp/activate/",
            {
                "activation_token": activation_token,
                "code": pyotp.TOTP(secret).now(),
                **extra,
            },
            format="json",
        )
        return secret, response

    def previous_code(self, secret):
        return pyotp.TOTP(secret).at(time.time() - 30)

    def test_activation_requires_current_password(self):
        # Act
        _, response = self.activate()

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data)
        self.assertFalse(is_mfa_enabled(self.user))

    def test_activation_rejects_wrong_password(self):
        # Act
        _, response = self.activate(password=generate_password())

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data)
        self.assertFalse(is_mfa_enabled(self.user))

    def test_activation_with_current_password_enables_mfa(self):
        # Act
        _, response = self.activate(password=self.password)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertIn("recovery_codes", response.data)
        self.assertTrue(is_mfa_enabled(self.user))

    def test_activation_is_refused_for_account_without_usable_password(self):
        # Arrange
        self.user.set_unusable_password()
        self.user.save(update_fields=["password"])

        # Act
        _, response = self.activate(password=self.password)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data)
        self.assertFalse(is_mfa_enabled(self.user))

    def test_library_views_are_not_reachable_through_another_prefix(self):
        # Act
        _, response = self.activate(prefix="/x")

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertFalse(is_mfa_enabled(self.user))

    def test_recovery_codes_require_authenticator_code(self):
        # Arrange
        secret, _ = self.activate(password=self.password)

        # Act
        missing = self.client.post("/api/auth/mfa/recovery-codes/", format="json")
        confirmed = self.client.post(
            "/api/auth/mfa/recovery-codes/",
            {"code": pyotp.TOTP(secret).now()},
            format="json",
        )

        # Assert
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(len(confirmed.data["codes"]), 10)

    def test_regenerating_recovery_codes_requires_authenticator_code(self):
        # Arrange
        secret, activation = self.activate(password=self.password)

        # Act
        missing = self.client.post(
            "/api/auth/mfa/recovery-codes/regenerate/", format="json"
        )
        confirmed = self.client.post(
            "/api/auth/mfa/recovery-codes/regenerate/",
            {"code": self.previous_code(secret)},
            format="json",
        )

        # Assert
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(confirmed.status_code, 200)
        self.assertNotEqual(
            set(confirmed.data["codes"]), set(activation.data["recovery_codes"])
        )

    def test_recovery_code_does_not_unlock_recovery_codes(self):
        # Arrange
        _, activation = self.activate(password=self.password)

        # Act
        response = self.client.post(
            "/api/auth/mfa/recovery-codes/",
            {"code": activation.data["recovery_codes"][0]},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 400)

    @patch.object(MFAChangeThrottle, "rate", "1/hour")
    def test_repeated_deactivation_attempts_are_throttled(self):
        # Arrange
        secret = generate_totp_secret()
        TOTP.activate(self.user, secret)
        self.client.post(
            "/api/auth/mfa/totp/deactivate/", {"code": "000000"}, format="json"
        )

        # Act
        response = self.client.post(
            "/api/auth/mfa/totp/deactivate/",
            {"code": pyotp.TOTP(secret).now()},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 429)
