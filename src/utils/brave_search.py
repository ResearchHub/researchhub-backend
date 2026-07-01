"""Minimal Brave Search API client.

A thin wrapper over Brave's Web Search REST endpoint, mirroring ``utils.openalex``
as a generic, cross-app external-integration client. It owns exactly one
capability -- turn a query into a short list of ranked web results (title, url,
description, age) -- and nothing about how those results are used.

Auth is a single ``X-Subscription-Token`` header carrying
``settings.BRAVE_SEARCH_API_KEY``. When the key is unset the client is
``configured is False`` and ``search`` returns ``[]`` rather than erroring, so a
caller can treat web search as an optional capability that is simply absent until
the key is provisioned.
"""

import logging

from django.conf import settings

from utils.retryable_requests import retryable_requests_session

logger = logging.getLogger(__name__)

_BRAVE_WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_DEFAULT_COUNT = 5
_MAX_COUNT = 20
_DEFAULT_TIMEOUT = 15


class BraveSearch:
    """Web search over the Brave Search API.

    Args:
        api_key: subscription token; defaults to ``settings.BRAVE_SEARCH_API_KEY``.
        timeout: per-request timeout in seconds.
    """

    def __init__(self, *, api_key: str | None = None, timeout: int = _DEFAULT_TIMEOUT):
        self._api_key = (
            api_key
            if api_key is not None
            else getattr(settings, "BRAVE_SEARCH_API_KEY", "")
        ) or ""
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        """True when an API key is present so ``search`` can reach Brave."""
        return bool(self._api_key)

    def search(self, query: str, *, count: int = _DEFAULT_COUNT) -> list[dict]:
        """Return up to ``count`` web results for ``query``.

        Each result is ``{"title", "url", "description", "age"}`` (``age`` is
        Brave's freshness string, e.g. ``"2 weeks ago"``, or ``""``). Returns
        ``[]`` when the client is unconfigured, the query is blank, or the request
        fails -- web search is best-effort grounding, never a hard dependency.
        """
        query = str(query or "").strip()
        if not query or not self.configured:
            return []
        count = max(1, min(int(count or _DEFAULT_COUNT), _MAX_COUNT))
        try:
            session = retryable_requests_session()
            response = session.get(
                _BRAVE_WEB_SEARCH_URL,
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self._api_key,
                },
                params={"q": query, "count": count},
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - a search miss must not break callers
            logger.warning("Brave search failed for %r: %s", query, exc)
            return []
        return _parse_web_results(payload, count)


def _parse_web_results(payload: object, count: int) -> list[dict]:
    """Project Brave's ``web.results`` into the compact result shape."""
    payload = payload if isinstance(payload, dict) else {}
    web = payload.get("web") if isinstance(payload.get("web"), dict) else {}
    results: list[dict] = []
    for item in web.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        results.append(
            {
                "title": str(item.get("title") or "").strip(),
                "url": url,
                "description": str(item.get("description") or "").strip(),
                "age": str(item.get("age") or "").strip(),
            }
        )
        if len(results) >= count:
            break
    return results
