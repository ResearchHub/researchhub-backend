"""Settings-backed limits for files attached to Research AI chats.

Every field is overridable via a ``RESEARCH_AI_FILE_*`` setting, read at call
time so per-test ``override_settings`` applies.
"""

from dataclasses import dataclass

from django.conf import settings

_SETTING_OVERRIDES = {
    "max_file_bytes": "RESEARCH_AI_FILE_MAX_BYTES",
    "max_text_chars": "RESEARCH_AI_FILE_MAX_TEXT_CHARS",
    "max_unsent_files": "RESEARCH_AI_FILE_MAX_UNSENT",
    "upload_url_ttl_seconds": "RESEARCH_AI_FILE_UPLOAD_URL_TTL_SECONDS",
    "download_url_ttl_seconds": "RESEARCH_AI_FILE_DOWNLOAD_URL_TTL_SECONDS",
    "processing_timeout_seconds": "RESEARCH_AI_FILE_PROCESSING_TIMEOUT_SECONDS",
    "unsent_ttl_seconds": "RESEARCH_AI_FILE_UNSENT_TTL_SECONDS",
}


@dataclass(frozen=True)
class AgentFileConfig:
    max_file_bytes: int = 25 * 1024 * 1024

    # About 125K tokens: an agent pages through it, never loads it whole.
    max_text_chars: int = 500_000

    # Uploads not yet sent with a message, per user; bounds abandoned storage.
    max_unsent_files: int = 20

    # Long enough for a 25 MB upload on a slow connection.
    upload_url_ttl_seconds: int = 15 * 60

    download_url_ttl_seconds: int = 5 * 60

    # A file still processing after this long has lost its task.
    processing_timeout_seconds: int = 5 * 60

    # Unsent uploads older than this are purged with their objects.
    unsent_ttl_seconds: int = 24 * 60 * 60

    @classmethod
    def from_settings(cls) -> "AgentFileConfig":
        defaults = cls()
        return cls(
            **{
                field: getattr(settings, setting, getattr(defaults, field))
                for field, setting in _SETTING_OVERRIDES.items()
            }
        )
