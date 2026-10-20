"""Which URLs a chat may fetch: those already in it, never one the model wrote.

A URL counts when it appears whole in the user's messages (where its scheme may
be left off), in a client tool's result, or in the provider's own web search
results. Text the model wrote -- its replies, tool inputs, code output -- does
not count, nor does a URL in a tool result that the model wrote into any tool
input, so the model cannot put note content into a URL it then fetches. URLs
are compared in yarl's canonical form, so equivalent spellings are one URL.
"""

import html
import ipaddress
import re
from collections.abc import Iterable, Iterator, Sequence
from urllib.parse import urldefrag, urlsplit

import yarl

from research_ai.services.agent.types import (
    Message,
    ServerToolBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

MAX_URL_CHARS = 2048
_INVALID_URL = "url is not a valid URL"
_SERVER_SEARCH_RESULT = "web_search_tool_result"
_SERVER_TOOL_USE = "server_tool_use"
# A URL in text runs to whitespace, a delimiter or its fragment.
_URL = re.compile(r"https?://[^\s<>\"'`|#]+", re.IGNORECASE)
# Punctuation that may end a sentence after a URL rather than belong to it.
_TRAILING = ".,;:!?)]}>*_'\""
# A URL the user wrote without its scheme: a word at a boundary, not the tail of a
# longer host or URL such as "www.example.org" or "?u=example.org".
_BARE = re.compile(r"(?<![^\s(\[{<\"'`*,;|])[^\s<>\"'`|#(\[{*,;]+[^\s<>\"'`|#]*")
_HOST_LABEL = re.compile(r"(?!-)[a-z0-9_-]{1,63}(?<!-)", re.IGNORECASE)


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
        # Raises on a port that is not a number from 0 to 65535.
        port = parts.port
    except ValueError:
        raise UrlNotAllowedError(_INVALID_URL)
    if port == 0:
        raise UrlNotAllowedError(_INVALID_URL)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise UrlNotAllowedError("only http and https URLs can be fetched")
    if not _valid_host(parts.hostname):
        raise UrlNotAllowedError(_INVALID_URL)
    if parts.username is not None or parts.password is not None:
        raise UrlNotAllowedError("URLs with credentials cannot be fetched")
    return url


def _valid_host(host: str) -> bool:
    """Whether ``host`` is an IP address or a DNS name, Unicode ones included."""
    if ":" in host:
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            return False
        return True
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    labels = ascii_host.removesuffix(".").split(".")
    return all(_HOST_LABEL.fullmatch(label) for label in labels)


def mentioned(url: str, context: Sequence[Message]) -> bool:
    """Whether ``url`` appears whole in the conversation's trusted text."""
    target = _canonical(url)
    if target is None:
        return False
    if target in _user_urls(context):
        return True
    return target in _tool_urls(context) - _written_urls(context)


def _user_urls(context: Sequence[Message]) -> set[str]:
    urls = set()
    for message in context:
        if message.role != "user":
            continue
        for block in message.content:
            if isinstance(block, TextBlock):
                for reading in _readings(block.text):
                    urls |= _urls_in(reading) | _bare_urls_in(reading)
    return urls


def _tool_urls(context: Sequence[Message]) -> set[str]:
    """URLs in client tool results and the provider's web search results."""
    return {
        url
        for message in context
        for block in message.content
        for text in _result_strings(message.role, block)
        for reading in _readings(text)
        for url in _urls_in(reading)
    }


def _result_strings(role: str, block) -> Iterable[str]:
    if role == "user" and isinstance(block, ToolResultBlock):
        return _strings(block.content)
    if (
        isinstance(block, ServerToolBlock)
        and (block.data or {}).get("type") == _SERVER_SEARCH_RESULT
    ):
        return _strings(block.data)
    return []


def _written_urls(context: Sequence[Message]) -> set[str]:
    """Every URL the model wrote into a tool input."""
    return {
        url
        for text in _model_inputs(context)
        # A tool may echo an input entity-encoded: "?a=1&amp;b=2".
        for reading in [*_readings(text), html.escape(text, quote=False)]
        for url in _urls_in(reading)
    }


def _model_inputs(context: Sequence[Message]) -> Iterator[str]:
    """The strings of every tool request the model made, client or server side."""
    for message in context:
        for block in message.content:
            if isinstance(block, ToolUseBlock):
                yield from _strings(block.input)
            elif (
                isinstance(block, ServerToolBlock)
                and (block.data or {}).get("type") == _SERVER_TOOL_USE
            ):
                yield from _strings(block.data.get("input"))


def _urls_in(text: str) -> set[str]:
    return {
        url
        for match in _URL.finditer(text)
        for form in _forms(match.group())
        if (url := _canonical(form))
    }


def _bare_urls_in(text: str) -> set[str]:
    return {
        url
        for match in _BARE.finditer(text)
        if "." in match.group() and "://" not in match.group()
        for form in _forms(match.group())
        # Typed without a scheme, it may be fetched over either.
        for scheme in ("https", "http")
        if (url := _canonical(f"{scheme}://{form}"))
    }


def _forms(token: str) -> Iterator[str]:
    """``token``, then without each trailing punctuation mark in turn."""
    yield token
    while token and token[-1] in _TRAILING:
        token = token[:-1]
        yield token


def _canonical(url: str) -> str | None:
    """``url`` in one spelling: lowercase scheme and host, no default port or
    fragment, "/" for an empty path, unreserved characters decoded."""
    try:
        parsed = yarl.URL(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.host:
        return None
    # yarl prints "https://host" without its root slash unless a query follows.
    if parsed.raw_path == "/" and not parsed.raw_query_string:
        parsed = parsed.with_path("/")
    return str(parsed.with_fragment(None))


def _readings(text: str) -> list[str]:
    # Unescaping alone would break raw URLs such as "?a=1&copy=2".
    return [text, html.unescape(text)] if "&" in text else [text]


def _strings(value) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
