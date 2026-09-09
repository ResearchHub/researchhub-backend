from unittest.mock import Mock

import requests
from django.test import SimpleTestCase, override_settings

from utils.turnstile import TurnstileService


@override_settings(TURNSTILE_SECRET_KEY="secret")
class TurnstileServiceTests(SimpleTestCase):
    def test_verify_returns_true_for_accepted_token(self):
        # Arrange
        session = Mock()
        session.post.return_value = _create_mock_response({"success": True})

        # Act
        result = TurnstileService(session=session).verify("good-token")

        # Assert
        self.assertTrue(result)

    def test_verify_returns_false_for_rejected_token(self):
        # Arrange
        session = Mock()
        session.post.return_value = _create_mock_response(
            {"success": False, "error-codes": ["invalid-input-response"]}
        )

        # Act
        result = TurnstileService(session=session).verify("bad-token")

        # Assert
        self.assertFalse(result)

    def test_verify_returns_false_when_siteverify_is_unreachable(self):
        # Arrange
        session = Mock()
        session.post.side_effect = requests.ConnectionError("boom")

        # Act
        result = TurnstileService(session=session).verify("good-token")

        # Assert
        self.assertFalse(result)


def _create_mock_response(payload):
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response
