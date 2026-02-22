from datetime import timedelta
from unittest.mock import Mock

import jwt as pyjwt
import requests
from authlib.integrations.base_client.errors import OAuthError
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
    ENDAOMENT_REDIRECT_URL="https://researchhub.com/callback",
    CORS_ORIGIN_WHITELIST=["https://test.com", "https://researchhub.com"],
    BASE_FRONTEND_URL="https://researchhub.com",
    SALT_KEY="test-salt-key",
)
class TestEndaomentService(TestCase):
    """
    Tests for the `EndaomentService`.
    """

    @staticmethod
    def _create_id_token(sub: str) -> str:
        """
        Create a minimal OIDC token JWT with a 'sub' claim.
        """
        return pyjwt.encode({"sub": sub}, "secret", algorithm="HS256")

    def setUp(self):
        self.mock_client = Mock()
        self.service = EndaomentService(client=self.mock_client)
        self.user = User.objects.create_user(username="testUser1")

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
        id_token = self._create_id_token("externalUserId1")
        self.mock_client.validate_state.return_value = {
            "user_id": self.user.id,
            "code_verifier": "verifier123",
            "return_url": "https://researchhub.com/done",
        }
        self.mock_client.fetch_token.return_value = TokenResponse(
            access_token="access_token",
            refresh_token="refresh_token",
            expires_in=3600,
            id_token=id_token,
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
        self.assertEqual(account.endaoment_user_id, "externalUserId1")

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

    def test_get_valid_access_token_expired_no_refresh_token(self):
        """
        Test that get_valid_access_token deletes the account and returns None
        when the access token is expired and no refresh token is available.
        """
        # Arrange
        EndaomentAccount.objects.create(
            user=self.user,
            access_token="expired_token",
            refresh_token=None,
            token_expires_at=timezone.now() - timedelta(hours=1),
        )

        # Act
        result = self.service.get_valid_access_token(self.user)

        # Assert
        self.assertIsNone(result)
        self.assertFalse(EndaomentAccount.objects.filter(user=self.user).exists())
        self.mock_client.refresh_access_token.assert_not_called()

    def test_get_valid_access_token_refresh_token_expired(self):
        """
        Test that get_valid_access_token returns None and deletes the account
        when refresh fails with invalid_grant.
        """
        # Arrange
        EndaomentAccount.objects.create(
            user=self.user,
            access_token="expired_token",
            refresh_token="expired_refresh",
            token_expires_at=timezone.now() - timedelta(hours=1),
        )
        self.mock_client.refresh_access_token.side_effect = OAuthError(
            error="invalid_grant"
        )

        # Act
        result = self.service.get_valid_access_token(self.user)

        # Assert
        self.assertIsNone(result)
        self.mock_client.refresh_access_token.assert_called_once_with("expired_refresh")
        self.assertFalse(EndaomentAccount.objects.filter(user=self.user).exists())

    def test_get_valid_access_token_refresh_oauth_error(self):
        """
        Test that get_valid_access_token returns None when refresh fails
        with an OAuthError, but does not delete the account for non-invalid_grant
        errors.
        """
        # Arrange
        EndaomentAccount.objects.create(
            user=self.user,
            access_token="expired_token",
            refresh_token="refresh_token",
            token_expires_at=timezone.now() - timedelta(hours=1),
        )
        self.mock_client.refresh_access_token.side_effect = OAuthError(
            error="server_error"
        )

        # Act
        result = self.service.get_valid_access_token(self.user)

        # Assert
        self.assertIsNone(result)
        # account should NOT be deleted for non-invalid_grant errors
        self.assertTrue(EndaomentAccount.objects.filter(user=self.user).exists())

    def test_get_valid_access_token_refresh_http_error_propagates(self):
        """
        Test that get_valid_access_token lets HTTP errors propagate
        so callers can distinguish a transient upstream failure from
        a missing Endaoment connection.
        """
        # Arrange
        EndaomentAccount.objects.create(
            user=self.user,
            access_token="expired_token",
            refresh_token="refresh_token",
            token_expires_at=timezone.now() - timedelta(hours=1),
        )
        response = Mock()
        response.status_code = 500  # fail with HTTP error
        self.mock_client.refresh_access_token.side_effect = (
            requests.exceptions.HTTPError(response=response)
        )

        # Act & Assert
        with self.assertRaises(requests.exceptions.HTTPError):
            self.service.get_valid_access_token(self.user)

        # account should not be deleted
        self.assertTrue(EndaomentAccount.objects.filter(user=self.user).exists())

    def test_get_user_funds_returns_funds(self):
        """
        Test get_user_funds returns funds from the client.
        """
        # Arrange
        EndaomentAccount.objects.create(
            user=self.user,
            access_token="valid_token",
            refresh_token="refresh_token",
            token_expires_at=timezone.now() + timedelta(hours=1),
        )
        self.mock_client.get_user_funds.return_value = [
            {"id": "fund-1", "name": "My Fund"}
        ]

        # Act
        result = self.service.get_user_funds(self.user)

        # Assert
        self.assertEqual(result, [{"id": "fund-1", "name": "My Fund"}])
        self.mock_client.get_user_funds.assert_called_once_with("valid_token")

    def test_get_user_funds_fails_without_account(self):
        """
        Test get_user_funds raises DoesNotExist when user has no account.
        """
        # Arrange & Act & Assert
        with self.assertRaises(EndaomentAccount.DoesNotExist):
            self.service.get_user_funds(self.user)

    def test_get_user_funds_refreshes_expired_token(self):
        """
        Test get_user_funds refreshes expired token before fetching funds.
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
        self.mock_client.get_user_funds.return_value = []

        # Act
        result = self.service.get_user_funds(self.user)

        # Assert
        self.assertEqual(result, [])
        self.mock_client.get_user_funds.assert_called_once_with("new_token")

    def test_transfer_between_funds(self):
        """
        Test transfer_between_funds delegates to client with access token.
        """
        # Arrange
        self.service.get_valid_access_token = Mock(return_value="token1")
        self.mock_client.create_async_entity_transfer.return_value = {"id": "transfer1"}

        # Act
        result = self.service.transfer_between_funds(
            user=self.user,
            origin_fund_id="fund1",
            destination_fund_id="fund2",
            amount_cents=1000,
        )

        # Assert
        self.assertEqual(result, {"id": "transfer1"})
        self.mock_client.create_async_entity_transfer.assert_called_once_with(
            access_token="token1",
            origin_fund_id="fund1",
            destination_fund_id="fund2",
            amount_in_cents=1000,
        )

    def test_transfer_between_funds_fails_without_connection(self):
        """
        Test transfer_between_funds raises when user has no connection.
        """
        # Arrange
        self.service.get_valid_access_token = Mock(return_value=None)

        # Act & Assert
        with self.assertRaises(EndaomentAccount.DoesNotExist):
            self.service.transfer_between_funds(
                user=self.user,
                origin_fund_id="fund1",
                destination_fund_id="fund2",
                amount_cents=1000,
            )

    def test_create_async_grant_fails_without_connection(self):
        """
        Test create_async_grant raises when user has no connection.
        """
        # Arrange
        self.service.get_valid_access_token = Mock(return_value=None)

        # Act & Assert
        with self.assertRaises(EndaomentAccount.DoesNotExist):
            self.service.create_grant(
                user=self.user,
                origin_fund_id="fund1",
                destination_org_id="org1",
                amount_cents=1000,
                purpose="fundraise1",
            )

    def test_create_async_grant_success(self):
        """
        Test create_async_grant delegates to client with access token.
        """
        # Arrange
        self.service.get_valid_access_token = Mock(return_value="token1")
        self.mock_client.create_async_grant.return_value = {"id": "transfer1"}

        # Act
        result = self.service.create_grant(
            user=self.user,
            origin_fund_id="fund1",
            destination_org_id="org1",
            amount_cents=1000,
            purpose="fundraise1",
        )

        # Assert
        self.assertEqual(result, {"id": "transfer1"})
        self.mock_client.create_async_grant.assert_called_once_with(
            access_token="token1",
            origin_fund_id="fund1",
            destination_org_id="org1",
            amount_in_cents=1000,
            purpose="fundraise1",
        )

    def test_extract_user_id_valid_token(self):
        """
        Test _extract_user_id returns 'sub' from a valid JWT.
        """
        # Arrange
        id_token = self._create_id_token("user_123")

        # Act
        actual = EndaomentService._extract_user_id(id_token)

        # Assert
        self.assertEqual(actual, "user_123")

    def test_extract_user_id_none_token(self):
        """
        Test _extract_user_id returns None for None input.
        """
        # Act
        actual = EndaomentService._extract_user_id(None)

        # Assert
        self.assertIsNone(actual)

    def test_extract_user_id_invalid_token(self):
        """
        Test _extract_user_id returns None for malformed JWT.
        """
        # Act
        actual = EndaomentService._extract_user_id("not-a-jwt")

        # Assert
        self.assertIsNone(actual)

    def test_extract_user_id_no_sub_claim(self):
        """
        Test _extract_user_id returns None when JWT has no 'sub' claim.
        """
        # Arrange
        token = pyjwt.encode({"name": "test"}, "secret", algorithm="HS256")

        # Act
        actual = EndaomentService._extract_user_id(token)

        # Assert
        self.assertIsNone(actual)

    @override_settings(ENDAOMENT_RH_FUND_IDS={1234: "rhFund1", 5678: "rhFund2"})
    def test_get_researchhub_fund_id(self):
        """
        Test get_researchhub_fund_id returns correct fund ID based on settings.
        """
        # Arrange & Act
        result = self.service._get_researchhub_fund_id(1234)

        # Assert
        self.assertEqual(result, "rhFund1")

    @override_settings(ENDAOMENT_RH_FUND_IDS={1234: "rhFund1"})
    def test_transfer_to_researchhub_fund(self):
        """
        Test transfer_to_researchhub_fund looks up the origin fund's chain ID,
        resolves the RH fund, and delegates to create_async_entity_transfer.
        """
        # Arrange
        self.service.get_valid_access_token = Mock(return_value="token1")
        self.mock_client.get_fund_by_id.return_value = {
            "id": "fund1",
            "chainId": 1234,
        }
        self.mock_client.create_async_entity_transfer.return_value = {"id": "transfer1"}

        # Act
        result = self.service.transfer_to_researchhub_fund(
            user=self.user,
            origin_fund_id="fund1",
            amount_cents=5000,
        )

        # Assert
        self.assertEqual(result, {"id": "transfer1"})
        self.mock_client.get_fund_by_id.assert_called_once_with("token1", "fund1")
        self.mock_client.create_async_entity_transfer.assert_called_once_with(
            access_token="token1",
            origin_fund_id="fund1",
            destination_fund_id="rhFund1",
            amount_in_cents=5000,
        )

    def test_transfer_to_researchhub_fund_fails_without_connection(self):
        """
        Test transfer_to_researchhub_fund raises when user has no connection.
        """
        # Arrange
        self.service.get_valid_access_token = Mock(return_value=None)

        # Act & Assert
        with self.assertRaises(EndaomentAccount.DoesNotExist):
            self.service.transfer_to_researchhub_fund(
                user=self.user,
                origin_fund_id="fund1",
                amount_cents=5000,
            )
        self.mock_client.get_fund_by_id.assert_not_called()

    def test_transfer_to_researchhub_fund_origin_fund_not_found(self):
        """
        Test transfer_to_researchhub_fund raises ValueError when origin fund
        is not found.
        """
        # Arrange
        self.service.get_valid_access_token = Mock(return_value="token1")
        self.mock_client.get_fund_by_id.return_value = None

        # Act & Assert
        with self.assertRaisesMessage(
            ValueError, "Origin fund with ID fund1 not found"
        ):
            self.service.transfer_to_researchhub_fund(
                user=self.user,
                origin_fund_id="fund1",
                amount_cents=5000,
            )
        self.mock_client.create_async_entity_transfer.assert_not_called()

    def test_transfer_to_researchhub_fund_no_rh_fund_for_chain(self):
        """
        Test transfer_to_researchhub_fund raises ValueError when no RH fund
        is configured for the origin fund's chain ID.
        """
        # Arrange
        self.service.get_valid_access_token = Mock(return_value="token1")
        self.mock_client.get_fund_by_id.return_value = {
            "id": "fund1",
            "chainId": 9999,
        }

        # Act & Assert
        with self.assertRaisesMessage(
            ValueError, "No ResearchHub fund configured for chain ID 9999"
        ):
            self.service.transfer_to_researchhub_fund(
                user=self.user,
                origin_fund_id="fund1",
                amount_cents=5000,
            )
        self.mock_client.create_async_entity_transfer.assert_not_called()

    def test_get_researchhub_fund_id_no_mapping(self):
        """
        Test get_researchhub_fund_id returns None when no mapping exists.
        """
        # Act & Assert
        with self.assertRaisesMessage(
            ValueError, "No ResearchHub fund configured for chain ID 9999"
        ):
            self.service._get_researchhub_fund_id(9999)

    def test_disconnect(self):
        """
        Test disconnect revokes the refresh token and deletes the account.
        """
        # Arrange
        EndaomentAccount.objects.create(
            user=self.user,
            access_token="token",
            refresh_token="refresh_token",
            token_expires_at=timezone.now() + timedelta(hours=1),
        )

        # Act
        result = self.service.disconnect(self.user)

        # Assert
        self.assertTrue(result)
        self.assertFalse(EndaomentAccount.objects.filter(user=self.user).exists())
        self.mock_client.revoke_token.assert_called_once_with("refresh_token")

    def test_disconnect_no_account_returns_false(self):
        """
        Test disconnect returns False when user has no account.
        """
        # Act
        result = self.service.disconnect(self.user)

        # Assert
        self.assertFalse(result)
        self.mock_client.revoke_token.assert_not_called()

    def test_disconnect_still_deletes_if_revoke_fails(self):
        """
        Test that the account is still deleted even if token revocation fails.
        """
        # Arrange
        EndaomentAccount.objects.create(
            user=self.user,
            access_token="token",
            refresh_token="refresh_token",
            token_expires_at=timezone.now() + timedelta(hours=1),
        )
        self.mock_client.revoke_token.side_effect = Exception("Network error")

        # Act
        result = self.service.disconnect(self.user)

        # Assert
        self.assertTrue(result)
        self.assertFalse(EndaomentAccount.objects.filter(user=self.user).exists())
