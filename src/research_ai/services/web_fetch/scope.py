"""Which URLs a chat may fetch: those already in it, never one the model wrote.

A URL counts when it appears whole in the user's messages, in a client tool's
result, or in the provider's own web search results. Text the model wrote --
its replies, tool inputs, code output -- does not count, nor does a tool
result's echo of a tool input, so the model cannot put note content into a
URL it then fetches.
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


class UrlNotAllowedError(ValueError):
    """The URL cannot be fetched; the message is written for the model."""


def clean_url(url) -> str:
    """``url`` without its fragment, if it is an http(s) URL with a host."""
    url = str(url or "").strip()
    if not url:
        raise UrlNotAllowedError("url is required")
    if len(url) > MAX_URL_CHARS:
        raise UrlNotAllowedError(f"url exceeds {MAX_URL_CHARS} characters")
    url = urldefrag(url).url
    try:
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
    candidates = [url]
    if urlsplit(url).path == "/":
        candidates.append(url[:-1])
    for text in _trusted_text(context):
        if "&" in text:
            text = html.unescape(text)
        for candidate in candidates:
            start = text.find(candidate)
            while start >= 0:
                if _URL_END.match(text, start + len(candidate)):
                    return True
                start = text.find(candidate, start + 1)
    return False


def _trusted_text(context: Sequence[Message]) -> Iterator[str]:
    inputs = {
        text
        for message in context
        for block in message.content
        if isinstance(block, ToolUseBlock)
        for text in _strings(block.input)
    }
    for message in context:
        for block in message.content:
            if message.role == "user" and isinstance(block, TextBlock):
                yield block.text
            elif message.role == "user" and isinstance(block, ToolResultBlock):
                yield from (
                    text for text in _strings(block.content) if text not in inputs
                )
            elif (
                isinstance(block, ServerToolBlock)
                and (block.data or {}).get("type") == _SERVER_SEARCH_RESULT
            ):
                yield from _strings(block.data)


def _strings(value) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
