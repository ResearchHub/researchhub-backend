from unittest.mock import Mock

from django.test import TestCase
from requests.exceptions import HTTPError, RequestException

from orcid.clients import OrcidClient
from orcid.tests.helpers import OrcidTestHelper


class OrcidClientTests(TestCase):

    def setUp(self):
        self.mock_session = Mock()
        self.client = OrcidClient(session=self.mock_session)

    def test_exchange_code_for_token_success(self):
        # Arrange
        self.mock_session.post.return_value = Mock(
            json=lambda: {"orcid": OrcidTestHelper.ORCID_ID, "access_token": "token"},
            raise_for_status=Mock()
        )

        # Act
        result = self.client.exchange_code_for_token("code", "id", "secret", "https://example.com")

        # Assert
        self.assertEqual(result["orcid"], OrcidTestHelper.ORCID_ID)
        self.assertIn("oauth/token", self.mock_session.post.call_args[0][0])

    def test_exchange_code_for_token_raises_on_failure(self):
        # Arrange
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = HTTPError("401")
        self.mock_session.post.return_value = mock_response

        # Act & Assert
        with self.assertRaises(HTTPError):
            self.client.exchange_code_for_token("code", "id", "secret", "https://example.com")

    def test_get_email_data_success(self):
        # Arrange
        self.mock_session.get.return_value = Mock(
            json=lambda: {"email": [{"email": "user@stanford.edu", "verified": True}]},
            raise_for_status=Mock()
        )

        # Act
        result = self.client.get_email_data(OrcidTestHelper.ORCID_ID, "token")

        # Assert
        self.assertEqual(result["email"][0]["email"], "user@stanford.edu")

    def test_get_email_data_returns_empty_on_error(self):
        # Arrange
        self.mock_session.get.side_effect = RequestException("API error")

        # Act
        result = self.client.get_email_data(OrcidTestHelper.ORCID_ID, "token")

        # Assert
        self.assertEqual(result, {})

    def test_get_works_success(self):
        # Arrange
        self.mock_session.get.return_value = Mock(
            json=lambda: {"group": [{"work-summary": []}]},
            raise_for_status=Mock()
        )

        # Act
        result = self.client.get_works(OrcidTestHelper.ORCID_ID)

        # Assert
        self.assertEqual(result, {"group": [{"work-summary": []}]})

    def test_get_works_returns_empty_on_error(self):
        # Arrange
        self.mock_session.get.side_effect = RequestException("API error")

        # Act
        result = self.client.get_works(OrcidTestHelper.ORCID_ID)

        # Assert
        self.assertEqual(result, {})

