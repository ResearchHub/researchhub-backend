"""Exa's contents API, which returns a page's text when our own request cannot.

Billed at $1 per 1,000 pages of text (exa.ai/pricing, read 2026-10-14).
"""

import httpx
from django.conf import settings

API_URL = "https://api.exa.ai/contents"
# Exa's crawl gets less than our own request's timeout leaves the call.
_LIVECRAWL_TIMEOUT_MS = 20_000


class FallbackError(Exception):
    """The fetch API returned no page; the message is safe to show the model."""


class ExaContents:
    """``text(url)`` through Exa; ``configured`` only with ``EXA_API_KEY`` set."""

    def __init__(
        self, *, api_key: str | None = None, client: httpx.Client | None = None
    ):
        self._api_key = api_key
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self._key())

    def text(self, url: str, *, max_chars: int, timeout: float) -> tuple[str, str]:
        """The page's ``(title, text)``. Raises ``FallbackError``."""
        try:
            response = self._http().post(
                API_URL,
                headers={"x-api-key": self._key()},
                json={
                    "urls": [url],
                    "text": {"maxCharacters": max_chars},
                    "livecrawlTimeout": _LIVECRAWL_TIMEOUT_MS,
                },
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            raise FallbackError(f"fetch service unreachable ({type(exc).__name__})")
        if response.status_code != 200:
            raise FallbackError(f"fetch service answered HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            raise FallbackError("fetch service returned invalid JSON")
        if not isinstance(body, dict):
            raise FallbackError("fetch service returned invalid JSON")
        status = next(iter(body.get("statuses") or []), None)
        if isinstance(status, dict) and status.get("status") == "error":
            error = status.get("error")
            tag = error.get("tag") if isinstance(error, dict) else None
            raise FallbackError(
                f"fetch service could not read the page ({tag or 'error'})"
            )
        result = next(iter(body.get("results") or []), None)
        if not isinstance(result, dict) or not str(result.get("text") or "").strip():
            raise FallbackError("fetch service returned no text")
        return str(result.get("title") or ""), str(result["text"])

    def _key(self) -> str:
        if self._api_key is not None:
            return self._api_key
        return getattr(settings, "EXA_API_KEY", "") or ""

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client()
        return self._client
