"""
Tests for ChemRxiv API client.
"""

from datetime import datetime
from unittest.mock import Mock, patch

import requests
from django.test import TestCase

from paper.ingestion.clients.chemrxiv import ChemRxivClient, ChemRxivConfig
from paper.ingestion.exceptions import FetchError, RetryExhaustedError, TimeoutError


class TestChemRxivClient(TestCase):
    """Test ChemRxiv API client."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = ChemRxivConfig(
            rate_limit=10.0,  # Fast rate limit for testing
            max_retries=1,  # Fewer retries for faster tests
            initial_backoff=0.1,
        )
        self.client = ChemRxivClient(self.config)

    def test_config_defaults(self):
        """Test default configuration values."""
        config = ChemRxivConfig()
        self.assertEqual(config.source_name, "chemrxiv")
        self.assertEqual(
            config.base_url, "https://chemrxiv.org/engage/chemrxiv/public-api/v1"
        )
        self.assertEqual(config.rate_limit, 1.0)
        self.assertEqual(config.page_size, 100)
        self.assertEqual(config.max_results_per_query, 1000)

    @patch("requests.Session.get")
    def test_fetch_success(self, mock_get):
        """Test successful fetch from API."""
        mock_response = Mock()
        mock_response.json.return_value = {"totalCount": 1, "itemHits": []}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = self.client.fetch("/items", {"limit": 10})

        self.assertEqual(result, {"totalCount": 1, "itemHits": []})
        mock_get.assert_called_once_with(
            f"{self.config.base_url}/items",
            params={"limit": 10},
            timeout=self.config.request_timeout,
            headers={"Accept": "application/json"},
        )

    @patch("requests.Session.get")
    def test_fetch_timeout(self, mock_get):
        """Test fetch timeout handling."""
        mock_get.side_effect = requests.Timeout()

        with self.assertRaises(TimeoutError) as context:
            self.client.fetch("/items")

        self.assertIn("Request timed out", str(context.exception))

    @patch("requests.Session.get")
    def test_fetch_request_error(self, mock_get):
        """Test fetch request error handling."""
        mock_get.side_effect = requests.RequestException("Connection error")

        with self.assertRaises(FetchError) as context:
            self.client.fetch("/items")

        self.assertIn("Failed to fetch", str(context.exception))

    def test_parse_item_hits_response(self):
        """Test parsing of itemHits response structure."""
        raw_data = {
            "totalCount": 2,
            "itemHits": [
                {
                    "item": {
                        "id": "123",
                        "doi": "10.26434/chemrxiv-2025-test1",
                        "title": "Test Paper 1",
                    }
                },
                {
                    "item": {
                        "id": "456",
                        "doi": "10.26434/chemrxiv-2025-test2",
                        "title": "Test Paper 2",
                    }
                },
            ],
        }

        papers = self.client.parse(raw_data)

        self.assertEqual(len(papers), 2)
        self.assertEqual(papers[0]["id"], "123")
        self.assertEqual(papers[0]["source"], "chemrxiv")
        self.assertEqual(papers[1]["id"], "456")
        self.assertEqual(papers[1]["source"], "chemrxiv")

    def test_parse_single_item_response(self):
        """Test parsing of single item response."""
        raw_data = {
            "id": "789",
            "doi": "10.26434/chemrxiv-2025-single",
            "title": "Single Paper",
        }

        papers = self.client.parse(raw_data)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["id"], "789")
        self.assertEqual(papers[0]["source"], "chemrxiv")

    def test_parse_empty_response(self):
        """Test parsing of empty response."""
        raw_data = {"totalCount": 0, "itemHits": []}

        papers = self.client.parse(raw_data)

        self.assertEqual(len(papers), 0)

    def test_parse_unexpected_structure(self):
        """Test parsing of unexpected response structure."""
        raw_data = {"unexpected": "structure"}

        papers = self.client.parse(raw_data)

        self.assertEqual(len(papers), 0)

    @patch("requests.Session.get")
    def test_fetch_recent_default_dates(self, mock_get):
        """Test fetch_recent with default date range."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "totalCount": 0,
            "itemHits": [],
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        papers = self.client.fetch_recent()

        self.assertEqual(papers, [])
        mock_get.assert_called_once()

        # Check that all required parameters were included
        call_args = mock_get.call_args
        params = call_args[1]["params"]
        self.assertIn("limit", params)
        self.assertIn("skip", params)  # Uses skip, not offset
        self.assertIn("sort", params)
        self.assertIn("searchDateFrom", params)
        self.assertIn("searchDateTo", params)

    @patch("requests.Session.get")
    def test_fetch_recent_with_dates(self, mock_get):
        """Test fetch_recent with specific date range."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "totalCount": 1,
            "itemHits": [
                {
                    "item": {
                        "id": "123",
                        "doi": "10.26434/chemrxiv-2025-dated",
                        "title": "Dated Paper",
                    }
                }
            ],
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        since = datetime(2025, 1, 1)
        until = datetime(2025, 1, 7)
        papers = self.client.fetch_recent(since=since, until=until, max_results=10)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["id"], "123")

        # Verify query string parameters
        call_args = mock_get.call_args
        params = call_args[1]["params"]
        self.assertIn("searchDateFrom", params)
        self.assertEqual(params["searchDateFrom"], "2025-01-01")
        self.assertIn("searchDateTo", params)
        self.assertEqual(params["searchDateTo"], "2025-01-07")

    @patch("requests.Session.get")
    def test_fetch_recent_pagination(self, mock_get):
        """Test fetch_recent handles pagination correctly."""
        # First page
        response1 = {
            "totalCount": 150,
            "itemHits": [
                {"item": {"id": str(i), "title": f"Paper {i}"}} for i in range(100)
            ],
        }
        # Second page (partial)
        response2 = {
            "totalCount": 150,
            "itemHits": [
                {"item": {"id": str(i), "title": f"Paper {i}"}} for i in range(100, 150)
            ],
        }

        mock_response1 = Mock()
        mock_response1.json.return_value = response1
        mock_response1.raise_for_status = Mock()

        mock_response2 = Mock()
        mock_response2.json.return_value = response2
        mock_response2.raise_for_status = Mock()

        mock_get.side_effect = [mock_response1, mock_response2]

        papers = self.client.fetch_recent(max_results=200)

        self.assertEqual(len(papers), 150)
        self.assertEqual(mock_get.call_count, 2)

    @patch("requests.Session.get")
    def test_retry_on_failure(self, mock_get):
        """Test that client retries on failure."""
        # First call fails, second succeeds
        mock_response_fail = Mock()
        mock_response_fail.raise_for_status.side_effect = requests.HTTPError(
            "Server error"
        )

        mock_response_success = Mock()
        mock_response_success.json.return_value = {"totalCount": 0, "itemHits": []}
        mock_response_success.raise_for_status = Mock()

        mock_get.side_effect = [
            requests.RequestException("Connection error"),
            mock_response_success,
        ]

        result = self.client.fetch_with_retry("/items")

        self.assertEqual(result, {"totalCount": 0, "itemHits": []})
        self.assertEqual(mock_get.call_count, 2)

    @patch("requests.Session.get")
    def test_retry_exhausted(self, mock_get):
        """Test that client raises RetryExhaustedError after max retries."""
        mock_get.side_effect = requests.RequestException("Persistent error")

        with self.assertRaises(RetryExhaustedError) as context:
            self.client.fetch_with_retry("/items")

        self.assertIn("Failed after", str(context.exception))
        # With max_retries=1, we expect 2 attempts (initial + 1 retry)
        self.assertEqual(mock_get.call_count, 2)
