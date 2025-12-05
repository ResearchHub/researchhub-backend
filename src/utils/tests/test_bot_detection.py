from unittest.mock import Mock

from django.test import TestCase
from rest_framework.exceptions import PermissionDenied

from utils.bot_detection import (
    calculate_browser_fingerprint,
    is_allowed_bot,
    is_blocked_user_agent,
    validate_request_headers,
)


class BotDetectionTests(TestCase):
    def setUp(self):
        self.request = Mock()
        self.request.META = {}

    def test_is_allowed_bot_googlebot(self):
        self.assertTrue(is_allowed_bot("Mozilla/5.0 (compatible; Googlebot/2.1)"))

    def test_is_allowed_bot_bingbot(self):
        self.assertTrue(is_allowed_bot("Mozilla/5.0 (compatible; bingbot/2.0)"))

    def test_is_allowed_bot_regular_browser(self):
        self.assertFalse(is_allowed_bot("Mozilla/5.0 (Windows NT 10.0; Win64; x64)"))

    def test_is_allowed_bot_empty(self):
        self.assertFalse(is_allowed_bot(""))

    def test_is_blocked_user_agent_python_requests(self):
        self.assertTrue(is_blocked_user_agent("python-requests/2.28.0"))

    def test_is_blocked_user_agent_curl(self):
        self.assertTrue(is_blocked_user_agent("curl/7.68.0"))

    def test_is_blocked_user_agent_scrapy(self):
        self.assertTrue(is_blocked_user_agent("scrapy/2.5.0"))

    def test_is_blocked_user_agent_empty(self):
        self.assertTrue(is_blocked_user_agent(""))

    def test_is_blocked_user_agent_allowed_bot(self):
        self.assertFalse(is_blocked_user_agent("Googlebot/2.1"))

    def test_is_blocked_user_agent_regular_browser(self):
        self.assertFalse(
            is_blocked_user_agent(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
        )

    def test_calculate_browser_fingerprint_missing_headers(self):
        self.request.META = {"HTTP_USER_AGENT": "Mozilla/5.0"}
        result = calculate_browser_fingerprint(self.request)
        self.assertTrue(result["suspicious"])
        self.assertIn("missing_accept_language", result["issues"])

    def test_calculate_browser_fingerprint_fake_chrome(self):
        self.request.META = {
            "HTTP_USER_AGENT": "Mozilla/5.0 Chrome/120.0.0.0",
        }
        result = calculate_browser_fingerprint(self.request)
        self.assertTrue(result["suspicious"])
        self.assertIn("fake_chrome_ua", result["issues"])

    def test_calculate_browser_fingerprint_valid_browser(self):
        self.request.META = {
            "HTTP_USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "HTTP_ACCEPT": "text/html,application/json",
            "HTTP_ACCEPT_LANGUAGE": "en-US,en;q=0.9",
            "HTTP_ACCEPT_ENCODING": "gzip, deflate, br",
        }
        result = calculate_browser_fingerprint(self.request)
        self.assertFalse(result["suspicious"])

    def test_validate_request_headers_blocks_python_requests(self):
        self.request.META = {
            "HTTP_USER_AGENT": "python-requests/2.28.0",
            "HTTP_X_FORWARDED_FOR": "192.168.1.1",
        }
        with self.assertRaises(PermissionDenied):
            validate_request_headers(self.request)

    def test_validate_request_headers_allows_googlebot(self):
        self.request.META = {
            "HTTP_USER_AGENT": "Mozilla/5.0 (compatible; Googlebot/2.1)",
            "HTTP_X_FORWARDED_FOR": "66.249.64.1",
        }
        try:
            validate_request_headers(self.request)
        except PermissionDenied:
            self.fail("Googlebot should be allowed")

    def test_validate_request_headers_allows_regular_browser(self):
        self.request.META = {
            "HTTP_USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "HTTP_ACCEPT": "text/html,application/json",
            "HTTP_ACCEPT_LANGUAGE": "en-US,en;q=0.9",
            "HTTP_ACCEPT_ENCODING": "gzip, deflate, br",
            "HTTP_X_FORWARDED_FOR": "192.168.1.1",
        }
        try:
            validate_request_headers(self.request)
        except PermissionDenied:
            self.fail("Regular browser should be allowed")

    def test_validate_request_headers_blocks_suspicious_headers(self):
        self.request.META = {
            "HTTP_USER_AGENT": "Mozilla/5.0 Chrome/120.0.0.0",
            "HTTP_X_FORWARDED_FOR": "192.168.1.1",
        }
        with self.assertRaises(PermissionDenied):
            validate_request_headers(self.request)

