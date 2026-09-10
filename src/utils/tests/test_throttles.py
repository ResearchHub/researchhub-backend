from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory

from utils.throttles import CloudflareAnonRateThrottle


class TwoPerMinuteCloudflareAnonRateThrottle(CloudflareAnonRateThrottle):
    rate = "2/minute"


class CloudflareAnonRateThrottleTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = APIRequestFactory()

    def tearDown(self):
        cache.clear()

    def test_prefers_cloudflare_connecting_ip(self):
        # Arrange
        request = self.factory.get(
            "/",
            HTTP_CF_CONNECTING_IP="203.0.113.10",
            HTTP_X_FORWARDED_FOR="198.51.100.20",
            REMOTE_ADDR="10.0.0.1",
        )

        # Act
        ident = CloudflareAnonRateThrottle().get_ident(request)

        # Assert
        self.assertEqual(ident, "203.0.113.10")

    def test_falls_back_to_remote_addr_without_cloudflare_header(self):
        # Arrange
        request = self.factory.get(
            "/",
            HTTP_X_FORWARDED_FOR="198.51.100.20",
            REMOTE_ADDR="10.0.0.1",
        )

        # Act
        ident = CloudflareAnonRateThrottle().get_ident(request)

        # Assert
        self.assertEqual(ident, "10.0.0.1")

    def test_falls_back_to_remote_addr_for_invalid_cloudflare_header(self):
        # Arrange
        request = self.factory.get(
            "/",
            HTTP_CF_CONNECTING_IP="not-an-ip",
            HTTP_X_FORWARDED_FOR="198.51.100.20",
            REMOTE_ADDR="10.0.0.1",
        )

        # Act
        with self.assertLogs("utils.throttles", level="WARNING"):
            ident = CloudflareAnonRateThrottle().get_ident(request)

        # Assert
        self.assertEqual(ident, "10.0.0.1")

    def test_bucket_cannot_be_bypassed_by_varying_xff(self):
        # Arrange
        results = []

        # Act
        for request_number in range(3):
            request = self.factory.get(
                "/",
                HTTP_CF_CONNECTING_IP="203.0.113.10",
                HTTP_X_FORWARDED_FOR=f"198.51.100.{request_number + 1}",
            )
            request.user = AnonymousUser()
            results.append(
                TwoPerMinuteCloudflareAnonRateThrottle().allow_request(request, None)
            )

        # Assert
        self.assertEqual(results, [True, True, False])
