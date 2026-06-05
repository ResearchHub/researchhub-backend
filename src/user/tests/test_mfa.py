import pyotp
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

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
