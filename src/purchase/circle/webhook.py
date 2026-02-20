import base64
import logging
import re

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_public_key
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

CIRCLE_PUBLIC_KEY_CACHE_TTL = 60 * 60  # 1 hour
CIRCLE_TOKEN_CACHE_TTL = 60 * 60  # 1 hour

_UUID_RE = re.compile(
    r"^[a-f0-9\-]{36}$",
    re.IGNORECASE,
)


class CircleTransientTokenValidationError(Exception):
    """Retryable failure while validating inbound token metadata with Circle."""

    pass


def _fetch_public_key(key_id: str) -> str:
    """Fetch a Circle notification public key by ID (base64-encoded DER)."""
    if not getattr(settings, "CIRCLE_API_KEY", None):
        raise ValueError("CIRCLE_API_KEY is not configured")

    api_base = settings.CIRCLE_API_BASE_URL
    url = f"{api_base}/v2/notifications/publicKey/{key_id}"
    headers = {"Authorization": f"Bearer {settings.CIRCLE_API_KEY}"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        logger.error(
            "Failed to fetch Circle public key for key_id=%s", key_id, exc_info=True
        )
        raise
    data = response.json()
    return data["data"]["publicKey"]


def _get_public_key_b64(key_id: str) -> str:
    """Get Circle's public key (base64 DER), using cache to avoid repeated API calls."""
    if not _UUID_RE.match(key_id):
        raise ValueError(f"Invalid Circle key_id format: {key_id!r}")

    cache_key = f"circle_webhook_pubkey:{key_id}"
    public_key_b64 = cache.get(cache_key)
    if public_key_b64 is None:
        public_key_b64 = _fetch_public_key(key_id)
        cache.set(cache_key, public_key_b64, CIRCLE_PUBLIC_KEY_CACHE_TTL)
    return public_key_b64


def _fetch_token(token_id: str) -> dict:
    """Fetch a Circle token object by token ID."""
    if not getattr(settings, "CIRCLE_API_KEY", None):
        raise ValueError("CIRCLE_API_KEY is not configured")

    api_base = settings.CIRCLE_API_BASE_URL
    url = f"{api_base}/v1/w3s/tokens/{token_id}"
    headers = {"Authorization": f"Bearer {settings.CIRCLE_API_KEY}"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        logger.error(
            "Failed to fetch Circle token for token_id=%s", token_id, exc_info=True
        )
        raise

    data = response.json()
    return data["data"]["token"]


def _get_token(token_id: str) -> dict:
    """Get Circle token details with a short cache TTL."""
    if not _UUID_RE.match(token_id):
        raise ValueError(f"Invalid Circle token_id format: {token_id!r}")

    cache_key = f"circle_webhook_token:{token_id}"
    token = cache.get(cache_key)
    if token is None:
        token = _fetch_token(token_id)
        cache.set(cache_key, token, CIRCLE_TOKEN_CACHE_TTL)
    return token


def _blockchain_family(blockchain: str) -> str | None:
    upper = (blockchain or "").upper()
    if upper.startswith("BASE"):
        return "BASE"
    if upper.startswith("ETH"):
        return "ETH"
    return None


def _expected_rsc_token_address(blockchain: str) -> str | None:
    family = _blockchain_family(blockchain)
    if family == "BASE":
        return (getattr(settings, "WEB3_BASE_RSC_ADDRESS", "") or "").lower() or None
    if family == "ETH":
        return (getattr(settings, "WEB3_RSC_ADDRESS", "") or "").lower() or None
    return None


def is_rsc_token(token_id: str, blockchain: str) -> bool:
    """
    Validate that token_id resolves to the configured RSC contract address for
    the inbound blockchain family.
    """
    expected_address = _expected_rsc_token_address(blockchain)
    if not expected_address:
        logger.error(
            "No expected RSC token address configured for blockchain=%s", blockchain
        )
        return False

    try:
        token = _get_token(token_id)
    except ValueError:
        # Invalid token identifiers are non-retryable and should be ignored.
        logger.warning(
            "Invalid Circle token_id format during validation: token_id=%r",
            token_id,
        )
        return False
    except Exception as exc:
        logger.warning(
            "Transient Circle token validation failure for token_id=%s blockchain=%s",
            token_id,
            blockchain,
            exc_info=True,
        )
        raise CircleTransientTokenValidationError from exc

    token_address = (token.get("tokenAddress") or "").lower()
    token_blockchain = token.get("blockchain")

    if not token_address:
        return False

    token_family = _blockchain_family(token_blockchain or "")
    webhook_family = _blockchain_family(blockchain)
    if token_family and webhook_family and token_family != webhook_family:
        return False

    return token_address == expected_address


def verify_webhook_signature(request_body: bytes, signature: str, key_id: str) -> bool:
    """
    Verify a Circle webhook ECDSA-SHA256 signature.

    Circle signs the raw request body with ECDSA using SHA-256. The public
    key is returned as base64-encoded DER from their API.

    See: https://developers.circle.com/wallets/webhook-notifications

    Args:
        request_body: The raw request body bytes.
        signature: The base64-encoded signature from X-Circle-Signature header.
        key_id: The key ID from X-Circle-Key-Id header.

    Returns:
        True if the signature is valid, False otherwise.
    """
    try:
        public_key_b64 = _get_public_key_b64(key_id)
        public_key = load_der_public_key(base64.b64decode(public_key_b64))

        signature_bytes = base64.b64decode(signature)

        public_key.verify(
            signature_bytes,
            request_body,
            ec.ECDSA(hashes.SHA256()),
        )
        return True
    except Exception:
        logger.warning("Circle webhook signature verification failed", exc_info=True)
        return False
