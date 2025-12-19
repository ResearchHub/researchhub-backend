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
