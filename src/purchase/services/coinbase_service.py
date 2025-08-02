import base64
import json
import logging
import time
from typing import Dict, List, Optional

import jwt
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from django.conf import settings

logger = logging.getLogger(__name__)


class CoinbaseService:
    """Service for handling Coinbase payment integration."""

    def __init__(self):
        self.api_key_name = getattr(settings, "COINBASE_API_KEY_NAME", None)
        self.api_key_secret = getattr(settings, "COINBASE_API_KEY_SECRET", None)
        self.api_url = getattr(
            settings, "COINBASE_API_URL", "https://api.developer.coinbase.com"
        )

    def _generate_jwt(self) -> str:
        """
        Generate a JWT token for Coinbase API authentication.

        Returns:
            JWT token as a string
        """
        if not self.api_key_name or not self.api_key_secret:
            raise ValueError("Coinbase API credentials not configured")

        # Load the private key
        private_key = serialization.load_pem_private_key(
            self.api_key_secret.encode("utf-8"),
            password=None,
        )

        # Create JWT claims
        issued_time = int(time.time())
        expiration_time = issued_time + 120  # 2 minutes expiration

        claims = {
            "sub": self.api_key_name,
            "iss": "coinbase-cloud",
            "aud": ["https://api.developer.coinbase.com"],
            "nbf": issued_time,
            "iat": issued_time,
            "exp": expiration_time,
        }

        # Generate JWT token
        token = jwt.encode(
            claims,
            private_key,
            algorithm="ES256",
            headers={
                "kid": self.api_key_name,
                "typ": "JWT",
                "alg": "ES256",
                "nonce": str(int(time.time() * 1000)),
            },
        )

        return token

    def generate_session_token(
        self,
        addresses: List[Dict[str, any]],
        assets: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """
        Generate a session token for Coinbase Onramp.

        Args:
            addresses: List of wallet addresses with their supported blockchains
                Example: [{"address": "0x123...", "blockchains": ["ethereum", "base"]}]
            assets: Optional list of supported assets (e.g., ["ETH", "USDC"])

        Returns:
            Dict containing the session token and channel_id
        """
        try:
            # Generate JWT for authentication
            jwt_token = self._generate_jwt()

            # Prepare request payload
            payload = {"addresses": addresses}
            if assets:
                payload["assets"] = assets

            # Make request to Coinbase API
            headers = {
                "Authorization": f"Bearer {jwt_token}",
                "Content-Type": "application/json",
            }

            response = requests.post(
                f"{self.api_url}/onramp/v1/token",
                headers=headers,
                json=payload,
                timeout=30,
            )

            if response.status_code != 200:
                logger.error(
                    f"Coinbase API error: {response.status_code} - {response.text}"
                )
                raise Exception(f"Failed to generate session token: {response.text}")

            data = response.json()
            return {
                "token": data.get("token"),
                "channel_id": data.get("channel_id", ""),
            }

        except Exception as e:
            logger.error(f"Error generating Coinbase session token: {str(e)}")
            raise
