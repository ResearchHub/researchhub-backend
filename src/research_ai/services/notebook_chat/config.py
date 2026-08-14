"""Settings-backed knobs for one notebook chat turn.

Every field is overridable via a ``RESEARCH_AI_NOTEBOOK_CHAT_*`` setting; the
defaults here are the production baseline. ``from_settings`` reads Django
settings at call time (not import time), so per-test ``override_settings``
takes effect on each run.
"""

from dataclasses import dataclass

from django.conf import settings

# field name -> the Django setting that overrides it.
_SETTING_OVERRIDES = {
    "max_iterations": "RESEARCH_AI_NOTEBOOK_CHAT_MAX_ITERATIONS",
    "max_tokens": "RESEARCH_AI_NOTEBOOK_CHAT_MAX_TOKENS",
    "temperature": "RESEARCH_AI_NOTEBOOK_CHAT_TEMPERATURE",
    "max_message_chars": "RESEARCH_AI_NOTEBOOK_CHAT_MAX_MESSAGE_CHARS",
}


@dataclass(frozen=True)
class NotebookChatConfig:
    """Knobs for one bounded notebook chat turn."""

    # One user turn is research + a handful of note edits, not a day-long
    # drafting run: enough iterations for read -> search -> edit -> reply
    # with retries, small enough that a runaway loop stays cheap.
    max_iterations: int = 30

    # One model turn's total output budget (thinking + text). None lets the
    # provider spend up to its model's output ceiling. Section replacement is
    # the normal edit path; the room remains useful for the explicitly retained
    # full-document fallback on unusual notes.
    max_tokens: int | None = None

    # Only forwarded to models that still accept sampling params and only when
    # thinking is off; the current Opus/Sonnet generations reject it outright.
    temperature: float = 1.0

    # Ceiling on one user chat message (bounds the seed prompt).
    max_message_chars: int = 20000

    @classmethod
    def from_settings(cls) -> "NotebookChatConfig":
        defaults = cls()
        return cls(
            **{
                field: getattr(settings, setting, getattr(defaults, field))
                for field, setting in _SETTING_OVERRIDES.items()
            }
        )
