import uuid
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from purchase.services.coinbase_service import CoinbaseService
from user.tests.helpers import create_user


@override_settings(
    COINBASE_API_KEY_ID="test_key_id",
    COINBASE_API_KEY_SECRET="test_key_secret",
)
class CoinbaseSecurityComplianceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user()
        self.client.force_authenticate(user=self.user)
        self.url = "/api/payment/coinbase/create-onramp/"
        self.valid_request_data = {
            "addresses": [
                {
                    "address": "0x742d35Cc6634C0532925a3b8D4C9db96C4b4d3b6",
                    "blockchains": ["base", "ethereum"],
                }
            ],
            "assets": ["ETH", "USDC"],
            "default_network": "base",
            "preset_fiat_amount": 100,
            "default_asset": "ETH",
        }

    @patch("purchase.services.coinbase_service.requests.post")
    @patch("purchase.services.coinbase_service.generate_jwt")
    def test_client_ip_extraction_and_coinbase_api_integration(
        self, mock_generate_jwt, mock_post
    ):
        mock_generate_jwt.return_value = "test_jwt_token"
        mock_response = Mock()
        mock_response.json.return_value = {
            "token": uuid.uuid4().hex,
            "channelId": "test_channel",
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        test_cases = [
            {
                "name": "X-Forwarded-For with multiple IPs",
                "headers": {"HTTP_X_FORWARDED_FOR": "203.0.113.195, 192.168.1.1"},
                "expected_ip": "203.0.113.195",
            },
            {
                "name": "REMOTE_ADDR fallback",
                "headers": {"REMOTE_ADDR": "192.0.2.146"},
                "expected_ip": "192.0.2.146",
            },
            {
                "name": "X-Forwarded-For takes precedence",
                "headers": {
                    "HTTP_X_FORWARDED_FOR": "203.0.113.100",
                    "REMOTE_ADDR": "192.168.1.50",
                },
                "expected_ip": "203.0.113.100",
            },
        ]

        for test_case in test_cases:
            with self.subTest(test_case=test_case["name"]):
                mock_post.reset_mock()

                response = self.client.post(
                    self.url,
                    data=self.valid_request_data,
                    format="json",
                    HTTP_ORIGIN="https://www.researchhub.com",
                    HTTP_USER_AGENT=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    ),
                    **test_case["headers"],
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)

                mock_post.assert_called_once()
                call_args = mock_post.call_args

                expected_url = "https://api.developer.coinbase.com/onramp/v1/token"
                self.assertIn(expected_url, str(call_args))

                headers = call_args[1]["headers"]
                self.assertTrue(headers["Authorization"].startswith("Bearer "))
                self.assertEqual(headers["Content-Type"], "application/json")

                request_body = call_args[1]["json"]
                actual_ip = request_body["clientIp"]
                expected_ip = test_case["expected_ip"]

                print(
                    f"✅ {test_case['name']}: Expected IP={expected_ip}, "
                    f"Actual IP={actual_ip}"
                )

                self.assertEqual(actual_ip, expected_ip)
                self.assertIn("addresses", request_body)
                self.assertIn("assets", request_body)

                cors_origin = response.get("Access-Control-Allow-Origin")
                self.assertEqual(cors_origin, "https://www.researchhub.com")
                self.assertNotEqual(cors_origin, "*")

    @patch("purchase.services.coinbase_service.CoinbaseService.generate_onramp_url")
    def test_cors_security_and_origin_validation(self, mock_service):
        mock_service.return_value = (
            "https://pay.coinbase.com/buy/select-asset?sessionToken=test"
        )

        response = self.client.post(
            self.url,
            data=self.valid_request_data,
            format="json",
            HTTP_USER_AGENT="ResearchHub-Mobile/1.0 (iOS; react-native)",
            HTTP_X_FORWARDED_FOR="192.168.1.100",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        cors_headers = [
            "Access-Control-Allow-Origin",
            "Access-Control-Allow-Credentials",
            "Access-Control-Allow-Methods",
            "Access-Control-Allow-Headers",
        ]
        for header in cors_headers:
            self.assertNotIn(header, response)
        print("✅ Mobile app correctly receives NO CORS headers")

        from django.conf import settings

        approved_origins = getattr(settings, "CORS_ORIGIN_WHITELIST", [])[:2]

        for origin in approved_origins:
            with self.subTest(origin=origin):
                response = self.client.post(
                    self.url,
                    data=self.valid_request_data,
                    format="json",
                    HTTP_ORIGIN=origin,
                    HTTP_USER_AGENT=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    ),
                    HTTP_X_FORWARDED_FOR="192.168.1.100",
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                cors_origin = response.get("Access-Control-Allow-Origin")
                self.assertEqual(cors_origin, origin)
                self.assertNotEqual(cors_origin, "*")
                print(f"✅ Approved origin {origin} gets exact CORS header")

        unauthorized_origins = [
            "https://malicious-site.com",
            "https://fake-researchhub.com",
        ]

        for origin in unauthorized_origins:
            with self.subTest(origin=origin):
                response = self.client.post(
                    self.url,
                    data=self.valid_request_data,
                    format="json",
                    HTTP_ORIGIN=origin,
                    HTTP_USER_AGENT=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    ),
                    HTTP_X_FORWARDED_FOR="192.168.1.100",
                )

                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                print(f"✅ Unauthorized origin {origin} correctly blocked with 403")

        response = self.client.options(
            self.url,
            HTTP_ORIGIN="https://www.researchhub.com",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.get("Access-Control-Allow-Origin"), "https://www.researchhub.com"
        )
        print("✅ Approved origin preflight works correctly")

        from django.test import RequestFactory

        from purchase.views.coinbase_view import CoinbaseViewSet

        factory = RequestFactory()
        request = factory.options(
            self.url,
            HTTP_ORIGIN="https://malicious-site.com",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )
        request.user = self.user

        view = CoinbaseViewSet()
        view.setup(request)
        response = view.create_onramp(request)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        print("✅ Unauthorized origin preflight correctly blocked")

    @patch("purchase.views.coinbase_view.get_client_ip")
    def test_security_failures_and_edge_cases(self, mock_get_ip):
        mock_get_ip.return_value = None
        print("❌ Testing request with NO client IP (should be rejected)")

        response = self.client.post(
            self.url,
            data=self.valid_request_data,
            format="json",
            HTTP_ORIGIN="https://www.researchhub.com",
            HTTP_USER_AGENT=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            ),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Unable to determine client IP", response.data["error"])
        print(
            f"✅ No IP correctly rejected: Status={response.status_code}, "
            f"Error='{response.data['error']}'"
        )

        self.client.force_authenticate(user=None)

        response = self.client.post(
            self.url,
            data=self.valid_request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        print("✅ Unauthenticated request correctly rejected with 401")


@override_settings(
    COINBASE_API_KEY_ID="test_key_id",
    COINBASE_API_KEY_SECRET="test_key_secret",
)
class CoinbaseServiceSecurityTests(TestCase):
    def setUp(self):
        self.service = CoinbaseService()
        self.valid_addresses = [
            {"address": "0x123456789", "blockchains": ["base", "ethereum"]}
        ]

    def test_service_layer_client_ip_requirements(self):
        with self.assertRaises(ValueError) as context:
            self.service.create_session_token(
                addresses=self.valid_addresses, client_ip=None
            )
        self.assertIn("Client IP is required", str(context.exception))
        print("✅ create_session_token correctly requires client_ip")

        with self.assertRaises(ValueError) as context:
            self.service.generate_onramp_url(
                addresses=self.valid_addresses, client_ip=None
            )
        self.assertIn("Client IP is required", str(context.exception))
        print("✅ generate_onramp_url correctly requires client_ip")

    @patch("purchase.services.coinbase_service.requests.post")
    @patch("purchase.services.coinbase_service.generate_jwt")
    def test_service_sends_client_ip_to_coinbase_api(
        self, mock_generate_jwt, mock_post
    ):
        mock_generate_jwt.return_value = "test_jwt_token"
        mock_response = Mock()
        mock_response.json.return_value = {
            "token": "session_token_123",
            "channelId": "test_channel",
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        client_ip = "192.168.1.100"

        self.service.create_session_token(
            addresses=self.valid_addresses, client_ip=client_ip
        )

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        request_body = call_args[1]["json"]

        self.assertEqual(request_body["clientIp"], client_ip)
        self.assertEqual(request_body["addresses"], self.valid_addresses)
        print(f"✅ Service layer sends client IP to Coinbase: {client_ip}")

        mock_post.reset_mock()
        result = self.service.generate_onramp_url(
            addresses=self.valid_addresses, client_ip=client_ip
        )

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        request_body = call_args[1]["json"]

        self.assertEqual(request_body["clientIp"], client_ip)
        self.assertIn("session_token_123", result)
        print(f"✅ generate_onramp_url also sends client IP: {client_ip}")
