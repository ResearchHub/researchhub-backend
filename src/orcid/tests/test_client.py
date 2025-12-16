from unittest.mock import Mock, patch

from django.test import TestCase

from orcid.clients.orcid_client import OrcidClient


@patch("orcid.clients.orcid_client.requests.post")
class OrcidClientTests(TestCase):

    def setUp(self):
        self.client = OrcidClient()

    def test_exchange_code_for_token_success(self, mock_post):
        # Arrange
        mock_post.return_value = Mock(
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

    def test_exchange_code_for_token_calls_correct_endpoint(self, mock_post):
        # Arrange
        mock_post.return_value = Mock(json=lambda: {}, raise_for_status=Mock())

        # Act
        self.client.exchange_code_for_token(
            code="code",
            client_id="id",
            client_secret="secret",
            redirect_uri="https://example.com"
        )

        # Assert
        call_args = mock_post.call_args
        self.assertIn("https://orcid.org/oauth/token", call_args[0][0])
        self.assertEqual(call_args[1]["timeout"], 30)
