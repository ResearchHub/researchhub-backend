import logging
import re
from functools import wraps
from typing import Any, Dict, List, Optional

import requests
from cdp.auth.utils.jwt import JwtOptions, generate_jwt
from django.conf import settings
from django.http import JsonResponse
from rest_framework import status

logger = logging.getLogger(__name__)


class CoinbaseService:
    """
    Service for handling Coinbase operations including JWT token generation and CORS
    security.
    """

    def __init__(self):
        """Initialize CoinbaseService with API credentials from settings."""
        self.api_key_id = getattr(settings, "COINBASE_API_KEY_ID", None)
        self.api_key_secret = getattr(settings, "COINBASE_API_KEY_SECRET", None)

        if not self.api_key_id or not self.api_key_secret:
            logger.warning("Coinbase API credentials not configured")

    @staticmethod
    def _get_approved_web_origins() -> List[str]:
        return getattr(settings, "CORS_ORIGIN_WHITELIST", [])

    @staticmethod
    def _is_origin_allowed_by_regex(origin: str) -> bool:
        allowed_regexes = getattr(settings, "CORS_ALLOWED_ORIGIN_REGEXES", [])
        for regex_pattern in allowed_regexes:
            if re.match(regex_pattern, origin):
                return True
        return False

    @staticmethod
    def _is_origin_approved(origin: str) -> bool:
        if not origin:
            return False

        approved_origins = CoinbaseService._get_approved_web_origins()
        if origin in approved_origins:
            return True

        return CoinbaseService._is_origin_allowed_by_regex(origin)

    @staticmethod
    def _create_cors_preflight_response(origin: str) -> JsonResponse:
        response = JsonResponse({"detail": "CORS preflight check passed"})
        response["Access-Control-Allow-Origin"] = origin
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    @staticmethod
    def _create_forbidden_response(message: str) -> JsonResponse:
        return JsonResponse({"error": message}, status=status.HTTP_403_FORBIDDEN)

    @staticmethod
    def _add_cors_headers_to_response(response, origin: str):
        response["Access-Control-Allow-Origin"] = origin
        return response

    @staticmethod
    def _handle_preflight_request(origin: str) -> JsonResponse:
        if CoinbaseService._is_origin_approved(origin):
            return CoinbaseService._create_cors_preflight_response(origin)

        logger.warning("Unauthorized CORS preflight attempt from origin")
        return CoinbaseService._create_forbidden_response("Origin not allowed")

    @staticmethod
    def _validate_post_request(origin: str) -> JsonResponse:
        if not origin:
            logger.warning("Request without origin header - blocked")
            return CoinbaseService._create_forbidden_response("Origin header required")

        if not CoinbaseService._is_origin_approved(origin):
            logger.warning("Blocked unauthorized request from origin")
            return CoinbaseService._create_forbidden_response("Origin not allowed")

        return None

    @staticmethod
    def _finalize_response(response, origin: str):
        if CoinbaseService._is_origin_approved(origin):
            logger.info("Added CORS headers for approved origin")
            return CoinbaseService._add_cors_headers_to_response(response, origin)

        return response

    @staticmethod
    def secure_coinbase_cors(view_func):

        @wraps(view_func)
        def wrapper(self, request, *args, **kwargs):
            origin = request.META.get("HTTP_ORIGIN", "")

            if request.method == "OPTIONS":
                return CoinbaseService._handle_preflight_request(origin)

            if request.method == "POST":
                forbidden_response = CoinbaseService._validate_post_request(origin)
                if forbidden_response:
                    return forbidden_response

            response = view_func(self, request, *args, **kwargs)

            return CoinbaseService._finalize_response(response, origin)

        return wrapper

    def generate_jwt_token(
        self,
        request_method: str,
        request_host: str,
        request_path: str,
        expires_in: int = 120,
    ) -> str:
        """
        Generate a JWT token for Coinbase API authentication.

        Args:
            request_method: HTTP method (GET, POST, etc.)
            request_host: The host for the API request
            request_path: The path for the API request
            expires_in: Token expiration time in seconds (default: 120)

        Returns:
            JWT token string

        Raises:
            ValueError: If API credentials are not configured
        """
        if not self.api_key_id or not self.api_key_secret:
            raise ValueError("Coinbase API credentials not configured")

        jwt_options = JwtOptions(
            api_key_id=self.api_key_id,
            api_key_secret=self.api_key_secret,
            request_method=request_method,
            request_host=request_host,
            request_path=request_path,
            expires_in=expires_in,
        )

        return generate_jwt(jwt_options)

    def create_session_token(
        self,
        addresses: List[Dict[str, Any]],
        assets: Optional[List[str]] = None,
        client_ip: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a single use token for initializing an Onramp or Offramp session.

        Args:
            addresses: List of address entries containing address and blockchains
                Example: [{"address": "0x123...", "blockchains": ["base", "ethereum"]}]
            assets: Optional list of asset tickers to restrict available assets
                Example: ["BTC", "ETH", "USDC"]
            client_ip: Client IP address for security verification

        Returns:
            Dict containing the session token and channel ID

        Raises:
            ValueError: If API credentials are not configured or client_ip is missing
            requests.RequestException: If API request fails
        """
        if not self.api_key_id or not self.api_key_secret:
            raise ValueError("Coinbase API credentials not configured")

        if not client_ip:
            raise ValueError("Client IP is required.")

        # Prepare request details
        request_method = "POST"
        request_host = "api.developer.coinbase.com"
        request_path = "/onramp/v1/token"

        # Generate JWT token for authorization
        jwt_token = self.generate_jwt_token(
            request_method=request_method,
            request_host=request_host,
            request_path=request_path,
            expires_in=120,
        )

        # Prepare request body
        request_body = {
            "addresses": addresses,
            "clientIp": client_ip,  # Required for security compliance
        }

        if assets:
            request_body["assets"] = assets

        # Make API request
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json",
        }

        url = f"https://{request_host}{request_path}"

        try:
            response = requests.post(
                url,
                headers=headers,
                json=request_body,
                timeout=30,
            )
            response.raise_for_status()

            return response.json()

        except requests.RequestException as e:
            logger.error(f"Failed to create session token: {e}")
            raise

    def generate_onramp_url(
        self,
        addresses: List[Dict[str, Any]],
        assets: Optional[List[str]] = None,
        default_network: Optional[str] = None,
        preset_fiat_amount: Optional[int] = None,
        preset_crypto_amount: Optional[float] = None,
        default_asset: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> str:
        """
        Generate a complete Onramp URL with session token.

        Args:
            addresses: List of address entries containing address and blockchains
            assets: Optional list of asset tickers to restrict available assets
            default_network: Default network to preselect (e.g., "base", "ethereum")
            preset_fiat_amount: Preset fiat amount in the currency
            preset_crypto_amount: Preset crypto amount
            default_asset: Default asset to preselect (e.g., "ETH", "USDC")
            client_ip: Client IP address for security verification
                (REQUIRED for compliance)

        Returns:
            Complete Onramp URL with session token

        Raises:
            ValueError: If API credentials are not configured or client_ip is missing
            requests.RequestException: If session token creation fails
        """
        # Create session token
        token_response = self.create_session_token(
            addresses=addresses,
            assets=assets,
            client_ip=client_ip,
        )

        session_token = token_response.get("token")
        if not session_token:
            raise ValueError("Failed to get session token from response")

        # Build Onramp URL
        base_url = "https://pay.coinbase.com/buy/select-asset"
        params = [f"sessionToken={session_token}"]

        if default_network:
            params.append(f"defaultNetwork={default_network}")
        if preset_fiat_amount is not None:
            params.append(f"presetFiatAmount={preset_fiat_amount}")
        if preset_crypto_amount is not None:
            params.append(f"presetCryptoAmount={preset_crypto_amount}")
        if default_asset:
            params.append(f"defaultAsset={default_asset}")

        query_string = "&".join(params)
        return f"{base_url}?{query_string}"
