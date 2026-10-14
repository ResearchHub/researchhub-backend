"""Settings-backed limits for the chat agents' web fetch.

Every field is overridable via a ``RESEARCH_AI_WEB_FETCH_*`` setting, read at
call time so per-test ``override_settings`` applies.
"""

from dataclasses import dataclass

from django.conf import settings

_SETTING_OVERRIDES = {
    "max_pdf_bytes": "RESEARCH_AI_WEB_FETCH_MAX_PDF_BYTES",
    "max_page_bytes": "RESEARCH_AI_WEB_FETCH_MAX_PAGE_BYTES",
    "timeout_seconds": "RESEARCH_AI_WEB_FETCH_TIMEOUT_SECONDS",
    "connect_timeout_seconds": "RESEARCH_AI_WEB_FETCH_CONNECT_TIMEOUT_SECONDS",
    "max_redirects": "RESEARCH_AI_WEB_FETCH_MAX_REDIRECTS",
    "min_page_chars": "RESEARCH_AI_WEB_FETCH_MIN_PAGE_CHARS",
    "fallback_timeout_seconds": "RESEARCH_AI_WEB_FETCH_FALLBACK_TIMEOUT_SECONDS",
    "max_fetches_per_turn": "RESEARCH_AI_WEB_FETCH_MAX_PER_TURN",
    "max_files_per_conversation": "RESEARCH_AI_WEB_FETCH_MAX_PER_CONVERSATION",
}


@dataclass(frozen=True)
class WebFetchConfig:
    # The upload cap: a fetched PDF is held to what a user could attach.
    max_pdf_bytes: int = 25 * 1024 * 1024

    # HTML and plain text; parsed in the worker itself, not a sandboxed child.
    max_page_bytes: int = 5 * 1024 * 1024

    # The whole direct request, redirects and body included.
    timeout_seconds: float = 20.0

    connect_timeout_seconds: float = 5.0

    max_redirects: int = 5

    # Letters and digits below which a direct page is a shell or a challenge.
    min_page_chars: int = 200

    fallback_timeout_seconds: float = 30.0

    max_fetches_per_turn: int = 10

    # Every fetched page is searched with the chat's attachments.
    max_files_per_conversation: int = 30

    @classmethod
    def from_settings(cls) -> WebFetchConfig:
        defaults = cls()
        return cls(
            **{
                field: getattr(settings, setting, getattr(defaults, field))
                for field, setting in _SETTING_OVERRIDES.items()
            }
        )
