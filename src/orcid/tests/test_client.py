from unittest.mock import Mock

from django.test import TestCase
from requests.exceptions import HTTPError

from orcid.clients.orcid_client import OrcidClient


class OrcidClientTests(TestCase):

    def setUp(self):
        self.mock_session = Mock()
        self.client = OrcidClient(session=self.mock_session)

    def test_exchange_code_for_token_success(self):
        # Arrange
        self.mock_session.post.return_value = Mock(
            json=lambda: {"orcid": "0000-0001-2345-6789", "access_token": "token"},
            raise_for_status=Mock()
        )

        # Act
        result = self.client.exchange_code_for_token(
            code="auth_code",
            client_id="client_id",
            client_secret="secret",
            redirect_uri="https://example.com/callback"
        )

        # Assert
        self.assertEqual(result["orcid"], "0000-0001-2345-6789")
        self.assertEqual(result["access_token"], "token")

    def test_exchange_code_for_token_calls_correct_endpoint(self):
        # Arrange
        self.mock_session.post.return_value = Mock(json=lambda: {}, raise_for_status=Mock())

        # Act
        self.client.exchange_code_for_token(
            code="code",
            client_id="id",
            client_secret="secret",
            redirect_uri="https://example.com"
        )

        # Assert
        call_args = self.mock_session.post.call_args
        self.assertIn("https://orcid.org/oauth/token", call_args[0][0])
        self.assertEqual(call_args[1]["timeout"], 30)

    def test_get_emails_returns_email_list(self):
        # Arrange
        self.mock_session.get.return_value = Mock(
            json=lambda: {"email": [{"email": "user@stanford.edu", "verified": True}]},
            raise_for_status=Mock()
        )

        # Act
        result = self.client.get_emails("0000-0001-2345-6789", "token")

        # Assert
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["email"], "user@stanford.edu")

    def test_get_emails_returns_empty_on_private(self):
        # Arrange
        self.mock_session.get.return_value = Mock(
            json=lambda: {"email": []},
            raise_for_status=Mock()
        )

        # Act
        result = self.client.get_emails("0000-0001-2345-6789", "token")

        # Assert
        self.assertEqual(result, [])

    def test_get_emails_returns_empty_on_error(self):
        # Arrange
        self.mock_session.get.side_effect = Exception("API error")

        # Act
        result = self.client.get_emails("0000-0001-2345-6789", "token")

        # Assert
        self.assertEqual(result, [])

