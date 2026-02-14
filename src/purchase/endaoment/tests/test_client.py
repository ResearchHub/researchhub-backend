import json
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from django.core import signing
from django.test import TestCase, override_settings

from purchase.endaoment.client import EndaomentClient, TokenResponse


@override_settings(
    ENDAOMENT_API_URL="https://api.dev.endaoment.org",
    ENDAOMENT_AUTH_URL="https://auth.dev.endaoment.org",
    ENDAOMENT_CLIENT_ID="test_client_id",
    ENDAOMENT_CLIENT_SECRET="test_client_secret",
    ENDAOMENT_REDIRECT_URL="https://researchhub.com/callback",
    CORS_ORIGIN_WHITELIST=["https://test.com", "https://researchhub.com"],
)
class TestEndaomentClient(TestCase):
    """
    Tests for the `EndaomentClient`.
    """

    FIXTURES_DIR = Path(__file__).parent / "fixtures"

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

    def test_get_user_funds(self):
        """
        Test fetching funds for a given user.
        """
        # Arrange
        with open(self.FIXTURES_DIR / "get_user_funds_response.json") as f:
            mock_funds = json.load(f)
        mock_response = Mock()
        mock_response.json.return_value = mock_funds
        mock_response.raise_for_status = Mock()
        self.client.http_session.request = Mock(return_value=mock_response)

        # Act
        result = self.client.get_user_funds(access_token="valid_access_token")

        # Assert
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result, mock_funds)
        self.client.http_session.request.assert_called_once_with(
            "GET",
            "https://api.dev.endaoment.org/v1/funds/mine",
            headers={"Authorization": "Bearer valid_access_token"},
            timeout=30,
        )

    def test_get_user_funds_fails_without_token(self):
        """
        Test fetching user funds fails without access token.
        """
        with self.assertRaises(ValueError):
            self.client.get_user_funds(access_token="")

    def test_get_fund_by_id(self):
        """
        Test fetching a specific fund by ID.
        """
        # Arrange
        with open(self.FIXTURES_DIR / "get_fund_by_id_response.json") as f:
            mock_fund = json.load(f)
        mock_response = Mock()
        mock_response.json.return_value = mock_fund
        mock_response.raise_for_status = Mock()
        self.client.http_session.request = Mock(return_value=mock_response)

        # Act
        result = self.client.get_fund_by_id(
            access_token="valid_access_token", fund_id="fund-123"
        )

        # Assert
        self.assertIsInstance(result, dict)
        self.assertEqual(result, mock_fund)
        self.client.http_session.request.assert_called_once_with(
            "GET",
            "https://api.dev.endaoment.org/v1/funds/fund-123",
            headers={"Authorization": "Bearer valid_access_token"},
            timeout=30,
        )

    def test_get_fund_by_id_not_found(self):
        """
        Test fetching a fund by ID that does not exist returns None.
        """
        # Arrange
        with open(self.FIXTURES_DIR / "get_fund_by_id_not_found_response.json") as f:
            mock_error_response = json.load(f)
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            response=Mock(status_code=404, json=lambda: mock_error_response)
        )
        self.client.http_session.request = Mock(return_value=mock_response)

        # Act
        result = self.client.get_fund_by_id(
            access_token="valid_access_token", fund_id="nonexistent-fund"
        )

        # Assert
        self.assertIsNone(result)
        self.client.http_session.request.assert_called_once_with(
            "GET",
            "https://api.dev.endaoment.org/v1/funds/nonexistent-fund",
            headers={"Authorization": "Bearer valid_access_token"},
            timeout=30,
        )

    def test_get_fund_by_id_fails_without_token(self):
        """
        Test fetching a fund by ID fails without access token.
        """
        with self.assertRaises(ValueError):
            self.client.get_fund_by_id(access_token="", fund_id="fund-123")

    @patch("purchase.endaoment.client.uuid.uuid4")
    def test_create_async_entity_transfer(self, mock_uuid):
        """
        Test creating an async entity transfer (grant).
        """
        # Arrange
        mock_uuid.return_value = Mock(hex="abc123")
        with open(
            self.FIXTURES_DIR / "create_async_entity_transfer_response.json"
        ) as f:
            mock_response_data = json.load(f)
        mock_response = Mock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status = Mock()
        self.client.http_session.request = Mock(return_value=mock_response)

        # Act
        result = self.client.create_async_entity_transfer(
            access_token="valid_access_token",
            origin_fund_id="fund-123",
            destination_fund_id="fund-456",
            amount_in_cents=50000,
            purpose="Support for research project",
        )

        # Assert
        self.assertEqual(result, mock_response_data)
        self.client.http_session.request.assert_called_once_with(
            "POST",
            "https://api.dev.endaoment.org/v1/transfers/async-entity-transfer",
            headers={"Authorization": "Bearer valid_access_token"},
            timeout=30,
            json={
                "idempotencyKey": "abc123",
                "originFundId": "fund-123",
                "destinationFundId": "fund-456",
                "requestedAmount": "50000",
                "purpose": "Support for research project",
            },
        )

    def test_create_async_entity_transfer_fails_without_token(self):
        """
        Test creating an async entity transfer fails without access token.
        """
        with self.assertRaises(ValueError):
            self.client.create_async_entity_transfer(
                access_token="",
                origin_fund_id="fund-123",
                destination_fund_id="fund-456",
                amount_in_cents=50000,
                purpose="Support for research project",
            )

    def test_create_async_entity_transfer_http_error(self):
        """
        Test that HTTP errors from the API are propagated when creating an async entity transfer.
        """
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            response=Mock(status_code=403)
        )
        self.client.http_session.request = Mock(return_value=mock_response)

        with self.assertRaises(requests.HTTPError):
            self.client.create_async_entity_transfer(
                access_token="valid_access_token",
                origin_fund_id="fund-123",
                destination_fund_id="fund-456",
                amount_in_cents=50000,
                purpose="Support for research project",
            )

    @patch("purchase.endaoment.client.uuid.uuid4")
    def test_create_async_grant(self, uuid_mock):
        """
        Test creating an async grant request.
        """
        # Arrange
        uuid_mock.return_value = Mock(hex="abc123")
        with open(self.FIXTURES_DIR / "create_async_grant_response.json") as f:
            mock_grant = json.load(f)
        mock_response = Mock()
        mock_response.json.return_value = mock_grant
        self.client.http_session.request = Mock(return_value=mock_response)

        # Act
        result = self.client.create_async_grant(
            access_token="valid_token",
            origin_fund_id="fund-1",
            destination_org_id="org-1",
            amount_in_cents=100000,
            purpose="Research funding",
        )

        # Assert
        self.assertEqual(result, mock_grant)
        self.client.http_session.request.assert_called_once_with(
            "POST",
            "https://api.dev.endaoment.org/v1/transfers/async-grants",
            headers={"Authorization": "Bearer valid_token"},
            timeout=30,
            json={
                "idempotencyKey": "abc123",
                "originFundId": "fund-1",
                "destinationOrgId": "org-1",
                "requestedAmount": "100000",
                "purpose": "Research funding",
            },
        )

    def test_create_async_grant_fails_without_token(self):
        """
        Test creating an async grant fails without access token.
        """
        # Act & Assert
        with self.assertRaises(ValueError):
            self.client.create_async_grant(
                access_token="",
                origin_fund_id="fund-1",
                destination_org_id="org-1",
                amount_in_cents=100000,
                purpose="Research funding",
            )

    def test_create_async_grant_http_error(self):
        """
        Test that HTTP errors from the API are propagated.
        """
        # Arrange
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            response=Mock(status_code=403)
        )
        self.client.http_session.request = Mock(return_value=mock_response)

        # Act & Assert
        with self.assertRaises(requests.HTTPError):
            self.client.create_async_grant(
                access_token="valid_token",
                origin_fund_id="fund-1",
                destination_org_id="org-1",
                amount_in_cents=100000,
                purpose="Research funding",
            )
