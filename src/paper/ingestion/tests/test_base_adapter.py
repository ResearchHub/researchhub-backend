"""
Tests for the base adapter class
"""

import time
from unittest.mock import MagicMock, patch

import pytest
from django.test import TestCase

from paper.ingestion.core.base_adapter import BaseAdapter, RateLimitExceeded


class ConcreteAdapter(BaseAdapter):
    """Concrete implementation for testing"""

    SOURCE_NAME = "test"
    DEFAULT_RATE_LIMIT = "10/s"
    BASE_URL = "https://api.test.com"

    def fetch_recent(self, hours=24):
        return [{"test": "data"}]

    def fetch_date_range(self, start_date, end_date):
        return [{"test": "data"}]

    def parse_response(self, response_data):
        return [{"title": "Test Paper"}]


class TestBaseAdapter(TestCase):
    """Test the base adapter functionality"""

    def setUp(self):
        self.adapter = ConcreteAdapter()

    def test_initialization(self):
        """Test adapter initialization"""
        self.assertEqual(self.adapter.SOURCE_NAME, "test")
        self.assertEqual(self.adapter.rate_limit, "10/s")
        self.assertIsNone(self.adapter.api_key)

    def test_initialization_with_api_key(self):
        """Test initialization with API key"""
        adapter = ConcreteAdapter(api_key="test-key-123")
        self.assertEqual(adapter.api_key, "test-key-123")

    def test_rate_limit_parsing(self):
        """Test rate limit string parsing"""
        # Test requests per second
        adapter = ConcreteAdapter(rate_limit="5/s")
        self.assertEqual(adapter.requests_per_period, 5)
        self.assertEqual(adapter.period_seconds, 1.0)
        self.assertEqual(adapter.min_time_between_requests, 0.2)

        # Test requests per minute
        adapter = ConcreteAdapter(rate_limit="60/m")
        self.assertEqual(adapter.requests_per_period, 60)
        self.assertEqual(adapter.period_seconds, 60.0)
        self.assertEqual(adapter.min_time_between_requests, 1.0)

        # Test requests per hour
        adapter = ConcreteAdapter(rate_limit="100/h")
        self.assertEqual(adapter.requests_per_period, 100)
        self.assertEqual(adapter.period_seconds, 3600.0)
        self.assertEqual(adapter.min_time_between_requests, 36.0)

    def test_rate_limiting_enforcement(self):
        """Test that rate limiting is enforced between requests"""
        adapter = ConcreteAdapter(rate_limit="10/s")  # 0.1 second between requests

        # First request should go through immediately
        start_time = time.time()
        adapter._enforce_rate_limit()
        first_delay = time.time() - start_time
        self.assertLess(first_delay, 0.01)  # Should be nearly instant

        # Second request should be delayed
        start_time = time.time()
        adapter._enforce_rate_limit()
        second_delay = time.time() - start_time
        self.assertGreaterEqual(second_delay, 0.09)  # Should wait at least 0.1 seconds

    @patch("paper.ingestion.core.base_adapter.httpx.Client")
    def test_make_request_success(self, mock_client_class):
        """Test successful HTTP request"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"result": "success"}'
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client_class.return_value = mock_client

        adapter = ConcreteAdapter()
        response = adapter._make_request("https://api.test.com/endpoint")

        self.assertEqual(response.text, '{"result": "success"}')
        mock_client.get.assert_called_once()

    @patch("paper.ingestion.core.base_adapter.httpx.Client")
    def test_make_request_rate_limit(self, mock_client_class):
        """Test handling of rate limit errors"""
        mock_response = MagicMock()
        mock_response.status_code = 429

        import httpx

        error = httpx.HTTPStatusError(
            message="Too Many Requests", request=MagicMock(), response=mock_response
        )

        mock_client = MagicMock()
        mock_client.get.side_effect = error
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client_class.return_value = mock_client

        adapter = ConcreteAdapter()

        with self.assertRaises(RateLimitExceeded):
            adapter._make_request("https://api.test.com/endpoint")

    @patch("paper.ingestion.core.base_adapter.httpx.Client")
    def test_make_request_with_api_key(self, mock_client_class):
        """Test that API key is included in headers when provided"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client_class.return_value = mock_client

        adapter = ConcreteAdapter(api_key="test-key-123")
        adapter._get_auth_headers = MagicMock(
            return_value={"Authorization": "Bearer test-key-123"}
        )

        adapter._make_request("https://api.test.com/endpoint")

        # Verify headers were passed
        call_args = mock_client.get.call_args
        self.assertIn("headers", call_args[1])

    def test_abstract_methods_implemented(self):
        """Test that concrete adapter implements all abstract methods"""
        adapter = ConcreteAdapter()

        # These should not raise NotImplementedError
        result = adapter.fetch_recent(24)
        self.assertIsNotNone(result)

        from datetime import datetime

        start = datetime(2024, 1, 1)
        end = datetime(2024, 1, 2)
        result = adapter.fetch_date_range(start, end)
        self.assertIsNotNone(result)

        result = adapter.parse_response({"data": "test"})
        self.assertIsNotNone(result)

    def test_fetch_by_id_not_implemented(self):
        """Test that fetch_by_id raises NotImplementedError by default"""
        adapter = ConcreteAdapter()

        with self.assertRaises(NotImplementedError):
            adapter.fetch_by_id("test-id")

    def test_validate_response(self):
        """Test response validation"""
        adapter = ConcreteAdapter()

        # Should return True for non-empty response
        self.assertTrue(adapter.validate_response({"data": "test"}))

        # Should return False for empty response
        self.assertFalse(adapter.validate_response({}))
        self.assertFalse(adapter.validate_response(None))

    def test_get_total_count(self):
        """Test getting total count from response"""
        adapter = ConcreteAdapter()

        # Default implementation returns None
        self.assertIsNone(adapter.get_total_count({"data": "test"}))
