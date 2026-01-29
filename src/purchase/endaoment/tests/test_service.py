from datetime import timedelta
from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase, override_settings
from django.utils import timezone

from purchase.endaoment import EndaomentService
from purchase.endaoment.client import TokenResponse
from purchase.related_models.endaoment_account_model import EndaomentAccount

User = get_user_model()


@override_settings(
    ENDAOMENT_AUTH_URL="https://auth.dev.endaoment.org",
    ENDAOMENT_CLIENT_ID="test_client_id",
    ENDAOMENT_CLIENT_SECRET="test_client_secret",
    ENDAOMENT_REDIRECT_URI="https://researchhub.com/callback",
    CORS_ORIGIN_WHITELIST=["https://test.com", "https://researchhub.com"],
    BASE_FRONTEND_URL="https://researchhub.com",
    SALT_KEY="test-salt-key",
)
class TestEndaomentService(TestCase):
    """
    Tests for the `EndaomentService`.
    """

    def setUp(self):
        self.mock_client = Mock()
        self.service = EndaomentService(client=self.mock_client)
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )

    def tearDown(self):
        EndaomentAccount.objects.all().delete()
        User.objects.all().delete()

    def test_get_authorization_url(self):
        """
        Test that get_authorization_url delegates to client.
        """
        # Arrange
        self.mock_client.build_authorization_url.return_value = (
            "https://auth.example.com"
        )

        # Act
        result = self.service.get_authorization_url(
            user_id=123, return_url="https://researchhub.com/dashboard"
        )

        # Assert
        self.assertEqual(result, "https://auth.example.com")
        self.mock_client.build_authorization_url.assert_called_once_with(
            123, "https://researchhub.com/dashboard"
        )

    def test_process_callback_with_error_returns_cancelled(self):
        """
        Test that an error parameter returns cancelled result.
        """
        # Arrange & Act
        result = self.service.process_callback(
            code="some_code", state="some_state", error="access_denied"
        )

        # Assert
        self.assertFalse(result.success)
        self.assertEqual(result.error, "cancelled")

    def test_process_callback_without_code_returns_cancelled(self):
        """
        Test that missing code returns cancelled result.
        """
        # Arrange & Act
        result = self.service.process_callback(code=None, state="some_state")

        # Assert
        self.assertFalse(result.success)
        self.assertEqual(result.error, "cancelled")

    def test_process_callback_with_invalid_state_returns_invalid_state(self):
        """
        Test that invalid state signature returns invalid_state error.
        """
        # Arrange
        self.mock_client.validate_state.side_effect = signing.BadSignature("Invalid")

        # Act
        result = self.service.process_callback(code="auth_code", state="invalid_state")

        # Assert
        self.assertFalse(result.success)
        self.assertEqual(result.error, "invalid_state")

    def test_process_callback_with_missing_user_id_returns_invalid_state(self):
        """
        Test that missing user_id in state returns invalid_state error.
        """
        # Arrange
        self.mock_client.validate_state.return_value = {
            "code_verifier": "verifier123"
            # missing user_id!
        }

        # Act
        result = self.service.process_callback(code="auth_code", state="valid_state")

        # Assert
        self.assertFalse(result.success)
        self.assertEqual(result.error, "invalid_state")

    def test_process_callback_with_missing_code_verifier_returns_invalid_state(self):
        """
        Test that missing code_verifier in state returns invalid_state error.
        """
        # Arrange
        self.mock_client.validate_state.return_value = {
            "user_id": 123
            # missing code_verifier!
        }

        # Act
        result = self.service.process_callback(code="auth_code", state="valid_state")

        # Assert
        self.assertFalse(result.success)
        self.assertEqual(result.error, "invalid_state")

    def test_process_callback_with_nonexistent_user_returns_error(self):
        """
        Test that a non-existent user returns error.
        """
        # Arrange
        self.mock_client.validate_state.return_value = {
            "user_id": 99999,
            "code_verifier": "verifier123",
        }
        self.mock_client.fetch_token.return_value = TokenResponse(
            access_token="access_token",
            refresh_token="refresh_token",
            expires_in=3600,
        )

        # Act
        result = self.service.process_callback(code="auth_code", state="valid_state")

        # Assert
        self.assertFalse(result.success)
        self.assertEqual(result.error, "error")

    def test_process_callback_success_creates_account(self):
        """
        Test successful callback creates EndaomentAccount.
        """
        # Arrange
        self.mock_client.validate_state.return_value = {
            "user_id": self.user.id,
            "code_verifier": "verifier123",
            "return_url": "https://researchhub.com/done",
        }
        self.mock_client.fetch_token.return_value = TokenResponse(
            access_token="access_token",
            refresh_token="refresh_token",
            expires_in=3600,
        )

        # Act
        result = self.service.process_callback(code="auth_code", state="valid_state")

        # Assert
        self.assertTrue(result.success)
        self.assertEqual(result.return_url, "https://researchhub.com/done")
        self.assertIsNone(result.error)

        account = EndaomentAccount.objects.get(user=self.user)
        self.assertEqual(account.access_token, "access_token")
        self.assertEqual(account.refresh_token, "refresh_token")

    def test_process_callback_success_updates_existing_account(self):
        """
        Test successful callback updates existing EndaomentAccount.
        """
        # Arrange
        EndaomentAccount.objects.create(
            user=self.user,
            access_token="old_token",
            refresh_token="old_refresh",
            token_expires_at=timezone.now(),
        )

        self.mock_client.validate_state.return_value = {
            "user_id": self.user.id,
            "code_verifier": "verifier123",
        }
        self.mock_client.fetch_token.return_value = TokenResponse(
            access_token="new_access_token",
            refresh_token="new_refresh_token",
            expires_in=7200,
        )

        # Act
        result = self.service.process_callback(code="auth_code", state="valid_state")

        # Assert
        self.assertTrue(result.success)

        account = EndaomentAccount.objects.get(user=self.user)
        self.assertEqual(account.access_token, "new_access_token")
        self.assertEqual(account.refresh_token, "new_refresh_token")

    def test_process_callback_fetch_token_failure_returns_error(self):
        """
        Test that fetch_token failure returns error.
        """
        # Arrange
        self.mock_client.validate_state.return_value = {
            "user_id": self.user.id,
            "code_verifier": "verifier123",
        }
        self.mock_client.fetch_token.side_effect = Exception("Token fetch failed")

        # Act
        result = self.service.process_callback(code="auth_code", state="valid_state")

        # Assert
        self.assertFalse(result.success)
        self.assertEqual(result.error, "error")

    def test_get_connection_status_connected(self):
        """
        Test connection status when user has an account.
        """
        # Arrange
        EndaomentAccount.objects.create(
            user=self.user,
            access_token="token",
            token_expires_at=timezone.now(),
            endaoment_user_id="endaoment_123",
        )

        # Act
        result = self.service.get_connection_status(self.user)

        # Assert
        self.assertTrue(result.connected)
        self.assertEqual(result.endaoment_user_id, "endaoment_123")

    def test_get_connection_status_not_connected(self):
        """
        Test connection status when user has no account.
        """
        # Arrange & Act
        result = self.service.get_connection_status(self.user)

        # Assert
        self.assertFalse(result.connected)
        self.assertIsNone(result.endaoment_user_id)

    def test_build_redirect_url_success(self):
        """
        Test building redirect URL for success case.
        """
        # Arrange & Act
        result = EndaomentService.build_redirect_url()

        # Assert
        self.assertEqual(result, "https://researchhub.com?endaoment_connected=true")

    def test_get_valid_access_token_no_account(self):
        """
        Test get_valid_access_token returns None when user has no account.
        """
        # Arrange & Act
        result = self.service.get_valid_access_token(self.user)

        # Assert
        self.assertIsNone(result)

    def test_get_valid_access_token(self):
        """
        Test get_valid_access_token returns token when not expired.
        """
        # Arrange
        EndaomentAccount.objects.create(
            user=self.user,
            access_token="valid_token",
            refresh_token="refresh_token",
            token_expires_at=timezone.now() + timedelta(hours=1),
        )

        # Act
        result = self.service.get_valid_access_token(self.user)

        # Assert
        self.assertEqual(result, "valid_token")
        self.mock_client.refresh_access_token.assert_not_called()

    def test_get_valid_access_token_expired_refreshes(self):
        """
        Test get_valid_access_token refreshes expired token.
        """
        # Arrange
        EndaomentAccount.objects.create(
            user=self.user,
            access_token="expired_token",
            refresh_token="refresh_token",
            token_expires_at=timezone.now() - timedelta(hours=1),
        )
        self.mock_client.refresh_access_token.return_value = TokenResponse(
            access_token="new_token",
            refresh_token="new_refresh",
            expires_in=3600,
        )

        # Act
        result = self.service.get_valid_access_token(self.user)

        # Assert
        self.assertEqual(result, "new_token")
        self.mock_client.refresh_access_token.assert_called_once_with("refresh_token")

        account = EndaomentAccount.objects.get(user=self.user)
        self.assertEqual(account.access_token, "new_token")
        self.assertEqual(account.refresh_token, "new_refresh")
