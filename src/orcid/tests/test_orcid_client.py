from unittest.mock import Mock

from django.test import TestCase
from requests.exceptions import HTTPError

from orcid.clients.orcid_client import OrcidClient
from orcid.tests.helpers import TEST_ORCID_ID


class OrcidClientTests(TestCase):

    def setUp(self):
        self.mock_session = Mock()
        self.client = OrcidClient(session=self.mock_session)

    def test_exchange_code_for_token_success(self):
        # Arrange
        self.mock_session.post.return_value = Mock(
            json=lambda: {"orcid": TEST_ORCID_ID, "access_token": "token"},
            raise_for_status=Mock()
        )

        # Act
        result = self.client.exchange_code_for_token("code", "id", "secret", "https://example.com")

        # Assert
        self.assertEqual(result["orcid"], TEST_ORCID_ID)
        self.assertIn("oauth/token", self.mock_session.post.call_args[0][0])

    def test_exchange_code_for_token_raises_on_failure(self):
        # Arrange
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = HTTPError("401")
        self.mock_session.post.return_value = mock_response

        # Act & Assert
        with self.assertRaises(HTTPError):
            self.client.exchange_code_for_token("code", "id", "secret", "https://example.com")

    def test_get_emails_success(self):
        # Arrange
        self.mock_session.get.return_value = Mock(
            json=lambda: {"email": [{"email": "user@stanford.edu", "verified": True}]},
            raise_for_status=Mock()
        )

        # Act
        result = self.client.get_emails(TEST_ORCID_ID, "token")

        # Assert
        self.assertEqual(result[0]["email"], "user@stanford.edu")

    def test_get_emails_returns_empty_on_error(self):
        # Arrange
        self.mock_session.get.side_effect = Exception("API error")

        # Act
        result = self.client.get_emails(TEST_ORCID_ID, "token")

        # Assert
        self.assertEqual(result, [])
