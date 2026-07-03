"""Unit tests for the Brave Search client (no network)."""

from unittest import TestCase
from unittest.mock import MagicMock, patch

from utils.brave_search import BraveSearch


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _session_returning(response):
    """A fake requests session whose ``.get`` returns ``response``."""
    session = MagicMock()
    session.get.return_value = response
    return session


class BraveSearchTests(TestCase):
    def test_unconfigured_reports_and_skips_request(self):
        # Arrange: no API key.
        client = BraveSearch(api_key="")

        # Act
        results = client.search("anything")

        # Assert: not configured, and an empty result without a request.
        self.assertFalse(client.configured)
        self.assertEqual(results, [])

    def test_blank_query_returns_empty(self):
        # Arrange
        client = BraveSearch(api_key="k")

        # Act / Assert
        self.assertEqual(client.search("   "), [])

    @patch("utils.brave_search.retryable_requests_session")
    def test_search_parses_web_results(self, mock_session_factory):
        # Arrange: a Brave-shaped payload with two results (one missing a URL).
        payload = {
            "web": {
                "results": [
                    {
                        "title": "Dataset SCP123",
                        "url": "https://singlecell.broadinstitute.org/scp123",
                        "description": "An MS white-matter snRNA-seq dataset.",
                        "age": "2 weeks ago",
                    },
                    {"title": "No URL", "description": "dropped"},
                ]
            }
        }
        session = _session_returning(_FakeResponse(payload))
        mock_session_factory.return_value = session
        client = BraveSearch(api_key="k")

        # Act
        results = client.search("MS white matter dataset", count=5)

        # Assert: only the well-formed result survives, projected to the shape.
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0],
            {
                "title": "Dataset SCP123",
                "url": "https://singlecell.broadinstitute.org/scp123",
                "description": "An MS white-matter snRNA-seq dataset.",
                "age": "2 weeks ago",
            },
        )
        # The subscription token is sent as the auth header.
        _, kwargs = session.get.call_args
        self.assertEqual(kwargs["headers"]["X-Subscription-Token"], "k")
        self.assertEqual(kwargs["params"]["q"], "MS white matter dataset")

    @patch("utils.brave_search.retryable_requests_session")
    def test_request_failure_returns_empty(self, mock_session_factory):
        # Arrange: the HTTP call raises.
        session = MagicMock()
        session.get.side_effect = RuntimeError("boom")
        mock_session_factory.return_value = session

        # Act
        results = BraveSearch(api_key="k").search("q")

        # Assert: swallowed to an empty list, not raised.
        self.assertEqual(results, [])
