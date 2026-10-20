"""Which URLs a chat may fetch: those already in it, never one the model wrote.

A URL counts when it appears whole in the user's messages, in a client tool's
result, or in the provider's own web search results. Text the model wrote --
its replies, tool inputs, code output -- does not count, nor does a URL in a
tool result that the model wrote into any tool input, so the model cannot put
note content into a URL it then fetches.
"""

import html
import re
from collections.abc import Iterable, Iterator, Sequence
from urllib.parse import urldefrag, urlsplit

from research_ai.services.agent.types import (
    Message,
    ServerToolBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

MAX_URL_CHARS = 2048
_SERVER_SEARCH_RESULT = "web_search_tool_result"
# What may follow a whole URL in text: its end, trailing punctuation, or a fragment.
_URL_END = re.compile(r"[.,;:!?)\]}>*_'\"]*(?:[\s<>\"'`|#]|$)")
_URL = re.compile(r"https?://[^\s<>\"'`|#]+", re.IGNORECASE)
_TRAILING = ".,;:!?)]}>*_'\""


class UrlNotAllowedError(ValueError):
    """The URL cannot be fetched; the message is written for the model."""


def clean_url(url) -> str:
    """``url`` without its fragment, if it is an http(s) URL with a host."""
    url = str(url or "").strip()
    if not url:
        raise UrlNotAllowedError("url is required")
    if len(url) > MAX_URL_CHARS:
        raise UrlNotAllowedError(f"url exceeds {MAX_URL_CHARS} characters")
    try:
        url = urldefrag(url).url
        parts = urlsplit(url)
    except ValueError:
        raise UrlNotAllowedError("url is not a valid URL")
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise UrlNotAllowedError("only http and https URLs can be fetched")
    if parts.username is not None or parts.password is not None:
        raise UrlNotAllowedError("URLs with credentials cannot be fetched")
    return url


def mentioned(url: str, context: Sequence[Message]) -> bool:
    """Whether ``url`` appears whole in the conversation's trusted text."""
    spellings = _spellings(url)
    return any(
        _contains_whole(text, spelling)
        for text in _trusted_text(context)
        for spelling in spellings
    )


def _spellings(url: str) -> list[str]:
    parts = urlsplit(url)
    # Only a URL ending at its root slash may be written without it.
    if parts.path == "/" and not (parts.query or parts.fragment) and url.endswith("/"):
        return [url, url[:-1]]
    return [url]


def _contains_whole(text: str, url: str) -> bool:
    start = text.find(url)
    while start >= 0:
        if _URL_END.match(text, start + len(url)):
            return True
        start = text.find(url, start + 1)
    return False


def _trusted_text(context: Sequence[Message]) -> Iterator[str]:
    written = _written_urls(context)
    for message in context:
        for block in message.content:
            echoes = written if isinstance(block, ToolResultBlock) else None
            for text in _trusted_strings(message.role, block):
                yield from _readings(text, echoes)


def _trusted_strings(role: str, block) -> Iterable[str]:
    if role == "user" and isinstance(block, TextBlock):
        return [block.text]
    if role == "user" and isinstance(block, ToolResultBlock):
        return _strings(block.content)
    if (
        isinstance(block, ServerToolBlock)
        and (block.data or {}).get("type") == _SERVER_SEARCH_RESULT
    ):
        return _strings(block.data)
    return []


def _written_urls(context: Sequence[Message]) -> re.Pattern | None:
    """Matches each whole URL the model wrote into a tool input."""
    urls = {
        match.group().rstrip(_TRAILING)
        for message in context
        for block in message.content
        if isinstance(block, ToolUseBlock)
        for text in _strings(block.input)
        for reading in _readings(text)
        for match in _URL.finditer(reading)
    }
    if not urls:
        return None
    # An input and its echo may each be entity-encoded or not: match both spellings.
    urls |= {html.escape(url, quote=False) for url in urls}
    # Longest first, so a URL is not cut at a shorter one it starts with.
    alternatives = "|".join(map(re.escape, sorted(urls, key=len, reverse=True)))
    return re.compile(f"(?:{alternatives})(?={_URL_END.pattern})", re.IGNORECASE)


def _readings(text: str, written: re.Pattern | None = None) -> list[str]:
    # Unescaping alone would break raw URLs such as "?a=1&copy=2".
    readings = [text, html.unescape(text)] if "&" in text else [text]
    if written is None:
        return readings
    # A tool may echo its input inside a longer string: "note <id> not found".
    return [written.sub(" ", reading) for reading in readings]


def _strings(value) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
