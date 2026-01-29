from unittest.mock import Mock, patch

from django.core import signing
from django.test import TestCase, override_settings

from purchase.endaoment.client import EndaomentClient, TokenResponse


@override_settings(
    ENDAOMENT_AUTH_URL="https://auth.dev.endaoment.org",
    ENDAOMENT_CLIENT_ID="test_client_id",
    ENDAOMENT_CLIENT_SECRET="test_client_secret",
    ENDAOMENT_REDIRECT_URI="https://researchhub.com/callback",
    CORS_ORIGIN_WHITELIST=["https://test.com", "https://researchhub.com"],
)
class TestEndaomentClient(TestCase):
    """
    Tests for the `EndaomentClient`.
    """

    def setUp(self):
        self.client = EndaomentClient()
        self.mock_session = Mock()

        self.session_patcher = patch.object(
            self.client, "_create_session", return_value=self.mock_session
        )
        self.token_patcher = patch(
            "purchase.endaoment.client.generate_token",
            return_value="test_code_verifier",
        )

        self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)
        self.token_patcher.start()
        self.addCleanup(self.token_patcher.stop)

    def test_create_session_returns_oauth2_session(self):
        """
        Test _create_session creates OAuth2Session with correct params.
        """
        # Use a fresh client to test the actual method (not mocked)
        client = EndaomentClient()

        session = client._create_session()

        self.assertEqual(session.client_id, "test_client_id")
        self.assertEqual(session.client_secret, "test_client_secret")

    def test_build_authorization_url(self):
        """
        Test building authorization URL.
        """
        # Arrange
        self.mock_session.create_authorization_url.return_value = (
            "https://auth.dev.endaoment.org/auth?state=xyz",
            "state_value",
        )

        # Act
        self.client.build_authorization_url(
            user_id=123, return_url="https://researchhub.com/dashboard"
        )

        # Assert
        call_kwargs = self.mock_session.create_authorization_url.call_args[1]
        state = call_kwargs["state"]
        state_data = signing.loads(state)

        self.assertEqual(state_data["user_id"], 123)
        self.assertEqual(state_data["return_url"], "https://researchhub.com/dashboard")
        self.assertEqual(state_data["code_verifier"], "test_code_verifier")

    def test_build_authorization_url_with_invalid_return_url(self):
        """
        Test building authorization URL with invalid return_url excludes it.
        """
        # Arrange
        self.mock_session.create_authorization_url.return_value = (
            "https://auth.dev.endaoment.org/auth?state=xyz",
            "state_value",
        )

        # Act
        self.client.build_authorization_url(
            user_id=123, return_url="https://malicious.com/phishing"
        )

        # Assert
        call_kwargs = self.mock_session.create_authorization_url.call_args[1]
        state = call_kwargs["state"]
        state_data = signing.loads(state)

        self.assertEqual(state_data["user_id"], 123)
        self.assertNotIn("return_url", state_data)

    def test_validate_state(self):
        """
        Test validating state
        """
        # Arrange
        state_data = {
            "user_id": 789,
            "code_verifier": "xyz789",
            "return_url": "https://example.com/done",
        }
        state = signing.dumps(state_data)

        # Act
        result = self.client.validate_state(state)

        # Assert
        self.assertEqual(result["user_id"], 789)
        self.assertEqual(result["return_url"], "https://example.com/done")

    def test_validate_state_invalid_signature(self):
        """
        Test validating an invalid state token.
        """
        with self.assertRaises(signing.BadSignature):
            self.client.validate_state("invalid_state_token")

    def test_fetch_token(self):
        """
        Test exchanging authorization code for tokens.
        """
        # Arrange
        self.mock_session.fetch_token.return_value = {
            "access_token": "access_123",
            "refresh_token": "refresh_456",
            "expires_in": 7200,
            "id_token": "id_token_789",
            "token_type": "Bearer",
        }

        # Act
        result = self.client.fetch_token(code="auth_code", code_verifier="verifier_123")

        # Assert
        self.assertIsInstance(result, TokenResponse)
        self.assertEqual(result.access_token, "access_123")
        self.assertEqual(result.refresh_token, "refresh_456")
        self.assertEqual(result.expires_in, 7200)
        self.assertEqual(result.id_token, "id_token_789")
        self.assertEqual(result.token_type, "Bearer")

        self.mock_session.fetch_token.assert_called_once_with(
            "https://auth.dev.endaoment.org/token",
            grant_type="authorization_code",
            code="auth_code",
            redirect_uri="https://researchhub.com/callback",
            code_verifier="verifier_123",
            timeout=30,
        )

    def test_refresh_access_token(self):
        """
        Test refreshing an expired access token.
        """
        # Arrange
        self.mock_session.refresh_token.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
            "id_token": "new_id_token",
        }

        # Act
        result = self.client.refresh_access_token(refresh_token="old_refresh_token")

        # Assert
        self.assertIsInstance(result, TokenResponse)
        self.assertEqual(result.access_token, "new_access_token")
        self.assertEqual(result.refresh_token, "new_refresh_token")
        self.assertEqual(result.expires_in, 3600)
        self.assertEqual(result.id_token, "new_id_token")

        self.mock_session.refresh_token.assert_called_once_with(
            "https://auth.dev.endaoment.org/token",
            refresh_token="old_refresh_token",
            timeout=30,
        )
