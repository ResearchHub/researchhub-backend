import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TIMEOUT_SECONDS = 10


class TurnstileService:
    """
    Service for verifying Cloudflare Turnstile tokens using Siteverify API.

    See: https://developers.cloudflare.com/turnstile/get-started/server-side-validation/
    """

    def __init__(self, session=None):
        self._session = session or requests
        self._secret_key = settings.TURNSTILE_SECRET_KEY

    def is_enabled(self) -> bool:
        """
        Returns whether Turnstile is enabled and properly configured.
        """
        return bool(settings.TURNSTILE_ENABLED and settings.TURNSTILE_SECRET_KEY)

    def verify(self, token: str, request=None) -> bool:
        """
        Checks whether the given `token` is valid.
        """
        if not token:
            return False

        payload = {"secret": self._secret_key, "response": token}
        # Use Cloudflare's IP address header which is set by Cloudflare at the edge.
        # See: https://developers.cloudflare.com/fundamentals/reference/http-headers/#cf-connecting-ip
        remote_ip = request and request.META.get("HTTP_CF_CONNECTING_IP")
        if remote_ip:
            payload["remoteip"] = remote_ip

        try:
            response = self._session.post(
                VERIFY_URL, data=payload, timeout=TIMEOUT_SECONDS
            )
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError):
            logger.exception("Turnstile siteverify failed")
            return False

        if not body.get("success"):
            logger.warning("Turnstile rejected token: %s", body.get("error-codes"))
            return False
        return True
