"""
Tests for OSF registration API client.
"""

from unittest import TestCase
from unittest.mock import Mock, patch

from paper.ingestion.clients.registrations.osf import OSFRegistrationClient
from paper.ingestion.exceptions import FetchError


def _response(status_code, payload=None):
    response = Mock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = payload
    return response


class TestOSFRegistrationClient(TestCase):
    def setUp(self):
        self.client = OSFRegistrationClient()

    @patch("requests.Session.get")
    def test_fetch_registration(self, mock_get):
        # Arrange
        registration = {
            "data": {
                "id": "wzubg",
                "attributes": {"title": "Plan title"},
                "relationships": {
                    "registration_schema": {"data": {"id": "schema1"}},
                },
                "embeds": {
                    "provider": {"data": {"attributes": {"name": "Lifecycle Journal"}}}
                },
                "links": {"html": "https://osf.io/wzubg/"},
            }
        }
        contributors = {
            "data": [
                {"embeds": {"users": {"data": {"attributes": {"full_name": "A B"}}}}},
                {"embeds": {"users": {"errors": [{"detail": "Not found."}]}}},
            ]
        }
        schema_blocks = {
            "data": [
                {
                    "attributes": {
                        "block_type": "question-label",
                        "schema_block_group_key": "g1",
                        "display_text": "Short Title:",
                    }
                },
                {
                    "attributes": {
                        "block_type": "long-text-input",
                        "schema_block_group_key": "g1",
                        "registration_response_key": "340-18",
                    }
                },
            ]
        }
        mock_get.side_effect = [
            _response(200, registration),
            _response(200, contributors),
            _response(200, schema_blocks),
        ]

        # Act
        record = self.client.fetch_registration("wzubg")

        # Assert
        self.assertEqual(
            record,
            {
                "id": "wzubg",
                "attributes": {"title": "Plan title"},
                "provider": "Lifecycle Journal",
                "url": "https://osf.io/wzubg/",
                "contributors": [{"full_name": "A B"}],
                "response_labels": {"340-18": "Short Title:"},
            },
        )

    @patch("requests.Session.get")
    def test_fetch_registration_not_public(self, mock_get):
        # Arrange
        mock_get.return_value = _response(401)

        # Act
        record = self.client.fetch_registration("abcde")

        # Assert
        self.assertIsNone(record)
        mock_get.assert_called_once()

    @patch("requests.Session.get")
    def test_fetch_registration_server_error(self, mock_get):
        # Arrange
        mock_get.return_value = _response(502)

        # Act & Assert
        with self.assertRaises(FetchError):
            self.client.fetch_registration("wzubg")
