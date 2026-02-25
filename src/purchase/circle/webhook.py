import base64
import logging
import re

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_public_key
from django.core.cache import cache

logger = logging.getLogger(__name__)

CIRCLE_PUBLIC_KEY_CACHE_TTL = 60 * 60  # 1 hour
_UUID_RE = re.compile(
    r"^[a-f0-9\-]{36}$",
    re.IGNORECASE,
)

# Known Circle token IDs for the RSC token, keyed by Circle blockchain identifier.
# These are stable identifiers assigned by Circle and do not change.
_RSC_TOKEN_ID_BY_BLOCKCHAIN = {
    # Testnet
    "BASE-SEPOLIA": "e7233cf0-a48c-5265-a9ad-6d125af58e71",
    "ETH-SEPOLIA": "979869da-9115-5f7d-917d-12d434e56ae7",
    # Production
    "BASE": "fe81326a-572d-5c31-9dde-31ef96a1220f",
    "ETH": "fa1e82a2-fd87-5030-aa61-e9447ce24570",
}


def _fetch_public_key(key_id: str) -> str:
    """Fetch a Circle notification public key by ID (base64-encoded DER)."""
    from purchase.circle.client import CircleWalletClient

    client = CircleWalletClient()
    try:
        return client.get_notification_public_key(key_id)
    except Exception:
        logger.error(
            "Failed to fetch Circle public key for key_id=%s", key_id, exc_info=True
        )
        raise


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


def is_rsc_token(token_id: str, blockchain: str) -> bool:
    """Check whether *token_id* is the known RSC token for *blockchain*."""
    expected = _RSC_TOKEN_ID_BY_BLOCKCHAIN.get(blockchain)
    return expected is not None and token_id == expected


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
    # Fetch the public key from Circle's API (or cache).  Network errors are
    # allowed to propagate so the view returns 500 and Circle retries.
    try:
        public_key_b64 = _get_public_key_b64(key_id)
    except ValueError:
        logger.warning("Invalid Circle key_id format: key_id=%s", key_id, exc_info=True)
        return False
    except Exception:
        logger.warning(
            "Transient error fetching Circle public key for key_id=%s",
            key_id,
            exc_info=True,
        )
        raise

    # Verify the ECDSA signature.  Cryptographic failures (bad key, bad
    # signature) are permanent and return False so the view returns 401.
    try:
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
