"""Web pages and PDFs the chat agents fetch, kept as chat files."""

from research_ai.services.web_fetch.config import WebFetchConfig
from research_ai.services.web_fetch.service import (
    DIRECT,
    FALLBACK,
    FetchedPage,
    WebFetchError,
    WebFetchService,
)

__all__ = [
    "DIRECT",
    "FALLBACK",
    "FetchedPage",
    "WebFetchConfig",
    "WebFetchError",
    "WebFetchService",
]
