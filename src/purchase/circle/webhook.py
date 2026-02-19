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
CIRCLE_API_BASE = "https://api.circle.com"


def _fetch_public_key(key_id: str) -> str:
    """Fetch a Circle notification public key by ID (base64-encoded DER)."""
    if not getattr(settings, "CIRCLE_API_KEY", None):
        raise ValueError("CIRCLE_API_KEY is not configured")

    url = f"{CIRCLE_API_BASE}/v2/notifications/publicKey/{key_id}"
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


_KEY_ID_RE = re.compile(r"^[a-f0-9\-]{36}$")


def _get_public_key_b64(key_id: str) -> str:
    """Get Circle's public key (base64 DER), using cache to avoid repeated API calls."""
    if not _KEY_ID_RE.match(key_id):
        raise ValueError(f"Invalid Circle key_id format: {key_id!r}")

    cache_key = f"circle_webhook_pubkey:{key_id}"
    public_key_b64 = cache.get(cache_key)
    if public_key_b64 is None:
        public_key_b64 = _fetch_public_key(key_id)
        cache.set(cache_key, public_key_b64, CIRCLE_PUBLIC_KEY_CACHE_TTL)
    return public_key_b64


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
