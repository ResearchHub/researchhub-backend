"""Fetching a web page or PDF for a chat agent and keeping it as an ``AgentFile``.

A page on an open-access host is requested directly from the worker; the
original response is stored in the private bucket and read like an attached
file, a PDF through the same extraction. Any other host, or a direct request
that is blocked, fails, or yields no readable text, gets the fetch API's text
instead (``Source.WEB_TEXT``).
Only URLs already in the conversation are fetched, by either path.
"""

import logging
import re
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlsplit

import httpx
from django.db import transaction
from django.utils.text import slugify

from research_ai.models import AgentConversation, AgentFile
from research_ai.models.agent_file import WEB_SOURCES
from research_ai.services.agent.types import Message
from research_ai.services.agent_files.config import AgentFileConfig
from research_ai.services.agent_files.extraction import PDF, UnreadableFileError
from research_ai.services.agent_files.extraction_service import TextExtractionService
from research_ai.services.agent_files.image_loader import KEY_PREFIX
from research_ai.services.agent_files.mistral_ocr import MistralOcr
from research_ai.services.web_fetch.config import WebFetchConfig
from research_ai.services.web_fetch.exa import ExaContents, FallbackError
from research_ai.services.web_fetch.html_text import (
    html_to_markdown,
    looks_like_challenge,
)
from research_ai.services.web_fetch.scope import (
    UrlNotAllowedError,
    clean_url,
    mentioned,
)
from researchhub.services.private_storage_service import PrivateStorageService
from utils.safe_http import UnsafeAddressError, public_http_client

logger = logging.getLogger(__name__)

DIRECT = "direct"
FALLBACK = "fallback"
USER_AGENT = (
    "ResearchHubBot/1.0 (+https://www.researchhub.com; fetches pages a "
    "user's research chat links to)"
)
_ACCEPT = "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.1"
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_TEXT_TYPES = frozenset({"text/plain", "text/markdown"})
# Served for PDFs by some hosts; the body's magic number decides.
_BINARY_TYPES = frozenset({"application/pdf", "application/octet-stream", ""})
_BLOCKED_STATUSES = frozenset({401, 403, 429, 503})
_MARKDOWN = "text/markdown"
_MAX_TITLE_CHARS = 255
_NOT_IN_CONVERSATION = (
    "{url} does not appear in this conversation. Only a URL the user gave or a "
    "search or tool result returned can be fetched; copy it exactly."
)


class WebFetchError(Exception):
    """The page could not be fetched; the message is written for the model."""


@dataclass(frozen=True)
class FetchedPage:
    file: AgentFile
    # ``DIRECT`` or ``FALLBACK``; how an earlier fetch got it when ``reused``.
    path: str
    reused: bool = False


@dataclass(frozen=True)
class _Document:
    data: bytes
    content_type: str
    extension: str
    title: str
    text: str
    truncated: bool
    final_url: str
    page_count: int | None = None
    pages_without_text: int | None = None


class _DirectFetchError(Exception):
    """The direct request got no usable page; the message names why."""


def _readable_chars(text: str) -> int:
    return sum(map(str.isalnum, text))


def _title(title: str, url: str) -> str:
    title = " ".join(title.split())
    if not title:
        parts = urlsplit(url)
        title = f"{parts.hostname}{parts.path if parts.path != '/' else ''}"
    return title[:_MAX_TITLE_CHARS]


def _key_name(url: str, extension: str) -> str:
    parts = urlsplit(url)
    stem = parts.path.rstrip("/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return (
        f"{slugify(stem)[:100] or slugify(parts.hostname or '') or 'page'}{extension}"
    )


def _content_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";")[0].strip().lower()


class WebFetchService:
    """Fetch, store and file a page; the tool wrapping it only formats results.

    ``http`` is an httpx client that must refuse non-public addresses (the
    default is ``public_http_client``); ``fallback`` is the fetch API
    client. Both, ``storage``, ``extraction`` and the configs are injectable.
    """

    def __init__(
        self,
        *,
        http: httpx.Client | None = None,
        fallback: ExaContents | None = None,
        storage: PrivateStorageService | None = None,
        extraction: TextExtractionService | None = None,
        config: WebFetchConfig | None = None,
        file_config: AgentFileConfig | None = None,
    ):
        self._http = http
        self.fallback = ExaContents() if fallback is None else fallback
        self.storage = PrivateStorageService() if storage is None else storage
        self._extraction = extraction
        self._config = config
        self._file_config = file_config

    @property
    def config(self) -> WebFetchConfig:
        return self._config or WebFetchConfig.from_settings()

    @property
    def file_config(self) -> AgentFileConfig:
        return self._file_config or AgentFileConfig.from_settings()

    @property
    def http(self) -> httpx.Client:
        if self._http is None:
            config = self.config
            self._http = public_http_client(
                timeout=httpx.Timeout(
                    config.timeout_seconds, connect=config.connect_timeout_seconds
                ),
                headers={"User-Agent": USER_AGENT, "Accept": _ACCEPT},
            )
        return self._http

    @property
    def extraction(self) -> TextExtractionService:
        return self._extraction or TextExtractionService(ocr=MistralOcr.from_settings())

    def fetch(
        self, url, *, conversation: AgentConversation, context: Sequence[Message]
    ) -> FetchedPage:
        """The page at ``url`` as a READY file of ``conversation``.

        ``context`` is the conversation so far, which must contain ``url``. A
        URL already fetched in the chat is not fetched again. Raises
        ``WebFetchError``.
        """
        try:
            url = clean_url(url)
        except UrlNotAllowedError as exc:
            raise WebFetchError(str(exc))
        if not mentioned(url, context):
            raise WebFetchError(_NOT_IN_CONVERSATION.format(url=url))
        fetched = self._scope(conversation)
        earlier = fetched.filter(source_url=url).order_by("-id").first()
        if earlier is not None:
            path = DIRECT if earlier.source == AgentFile.Source.WEB else FALLBACK
            return FetchedPage(file=earlier, path=path, reused=True)
        config = self.config
        if fetched.count() >= config.max_files_per_conversation:
            raise WebFetchError(
                f"This chat has fetched {config.max_files_per_conversation} pages, "
                "its limit. Work from those, or ask the user to start a new chat."
            )
        if conversation.user_id is None:
            raise WebFetchError("This chat has no owner to keep the page for.")
        if not self.storage.configured:
            raise WebFetchError("Web fetch is not available in this deployment.")
        host = urlsplit(url).hostname
        started = time.monotonic()
        try:
            document = self._direct(url, started + config.timeout_seconds)
        except UnsafeAddressError as exc:
            logger.info("web_fetch refused host=%s: %s", host, exc)
            raise WebFetchError(f"{url} cannot be fetched: {exc}.")
        except _DirectFetchError as exc:
            reason = str(exc)
        else:
            file = self._store(conversation, url, document, AgentFile.Source.WEB)
            self._log(DIRECT, host, started)
            return FetchedPage(file=file, path=DIRECT)
        document = self._fallback(url, reason, host, started)
        file = self._store(conversation, url, document, AgentFile.Source.WEB_TEXT)
        self._log(FALLBACK, host, started, reason)
        return FetchedPage(file=file, path=FALLBACK)

    # -- direct path ------------------------------------------------------

    def _direct(self, url: str, deadline: float) -> _Document:
        current = url
        for _ in range(self.config.max_redirects + 1):
            if not self.config.allows_direct(current):
                raise _DirectFetchError("not an open-access host")
            if time.monotonic() > deadline:
                raise _DirectFetchError("timed out")
            try:
                response = self.http.send(
                    self.http.build_request("GET", current), stream=True
                )
            except httpx.HTTPError as exc:
                raise _DirectFetchError(f"request failed ({type(exc).__name__})")
            try:
                if not response.is_redirect:
                    return self._document(response, current, deadline)
                location = response.headers.get("location")
            finally:
                response.close()
            if not location:
                raise _DirectFetchError("redirect without a location")
            current = urldefrag(urljoin(current, location)).url
            try:
                clean_url(current)
            except UrlNotAllowedError:
                raise _DirectFetchError("redirected to a URL that cannot be fetched")
        raise _DirectFetchError("too many redirects")

    def _document(
        self, response: httpx.Response, url: str, deadline: float
    ) -> _Document:
        status = response.status_code
        if status in _BLOCKED_STATUSES or response.headers.get("cf-mitigated"):
            raise _DirectFetchError(f"blocked (HTTP {status})")
        if not 200 <= status < 300:
            raise _DirectFetchError(f"HTTP {status}")
        content_type = _content_type(response)
        config = self.config
        if content_type in _BINARY_TYPES:
            data = self._body(response, config.max_pdf_bytes, deadline)
            if not data.startswith(b"%PDF-"):
                raise _DirectFetchError(
                    f"unsupported content type {content_type or 'none'}"
                )
            return self._pdf(data, url)
        if content_type not in _HTML_TYPES | _TEXT_TYPES:
            raise _DirectFetchError(f"unsupported content type {content_type}")
        data = self._body(response, config.max_page_bytes, deadline)
        if data.startswith(b"%PDF-"):
            return self._pdf(data, url)
        if content_type in _HTML_TYPES:
            if looks_like_challenge(data):
                raise _DirectFetchError("bot challenge page")
            title, text = html_to_markdown(
                data, base_url=url, encoding=response.charset_encoding
            )
            stored_type, extension = "text/html", ".html"
        else:
            title = ""
            text = data.decode(response.charset_encoding or "utf-8", "replace")
            stored_type, extension = content_type, ".txt"
        if _readable_chars(text) < config.min_page_chars:
            raise _DirectFetchError("no readable text")
        max_chars = self.file_config.max_text_chars
        return _Document(
            data=data,
            content_type=stored_type,
            extension=extension,
            title=title,
            text=text.replace("\x00", "")[:max_chars],
            truncated=len(text) > max_chars,
            final_url=url,
        )

    def _body(self, response: httpx.Response, max_bytes: int, deadline: float) -> bytes:
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > max_bytes:
            raise _DirectFetchError("too large")
        body = bytearray()
        try:
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > max_bytes:
                    raise _DirectFetchError("too large")
                if time.monotonic() > deadline:
                    raise _DirectFetchError("timed out")
        except httpx.HTTPError as exc:
            raise _DirectFetchError(f"download failed ({type(exc).__name__})")
        return bytes(body)

    def _pdf(self, data: bytes, url: str) -> _Document:
        try:
            extracted = self.extraction.extract(
                data, PDF, max_chars=self.file_config.max_text_chars
            )
        except UnreadableFileError:
            raise _DirectFetchError("no readable text")
        except Exception:
            logger.exception("fetched PDF could not be read")
            raise _DirectFetchError("the PDF could not be read")
        return _Document(
            data=data,
            content_type=PDF.content_type,
            extension=".pdf",
            title="",
            text=extracted.text,
            truncated=extracted.truncated,
            final_url=url,
            page_count=extracted.page_count,
            pages_without_text=len(extracted.pages_without_text),
        )

    # -- fallback path ----------------------------------------------------

    def _fallback(self, url: str, reason: str, host, started: float) -> _Document:
        failed = f"Could not fetch {url}: {reason}"
        if not self.fallback.configured:
            self._log("failed", host, started, reason)
            raise WebFetchError(f"{failed}.")
        max_chars = self.file_config.max_text_chars
        try:
            title, text = self.fallback.text(
                url,
                max_chars=max_chars,
                timeout=self.config.fallback_timeout_seconds,
            )
        except FallbackError as exc:
            self._log("failed", host, started, f"{reason}; {exc}")
            raise WebFetchError(f"{failed}; {exc}.")
        text = text.replace("\x00", "")
        return _Document(
            data=text.encode(),
            content_type=_MARKDOWN,
            extension=".md",
            title=title,
            text=text[:max_chars],
            truncated=len(text) > max_chars,
            final_url=url,
        )

    # -- storage ----------------------------------------------------------

    def _store(
        self, conversation: AgentConversation, url: str, document: _Document, source
    ) -> AgentFile:
        key = (
            f"{KEY_PREFIX}users/{conversation.user_id}/web/{uuid.uuid4()}/"
            f"{_key_name(document.final_url, document.extension)}"
        )
        etag = self.storage.write(
            key, document.data, content_type=document.content_type
        )
        try:
            with transaction.atomic():
                return AgentFile.objects.create(
                    user_id=conversation.user_id,
                    conversation=conversation,
                    source=source,
                    source_url=url,
                    filename=_title(document.title, document.final_url),
                    content_type=document.content_type,
                    size_bytes=len(document.data),
                    storage_key=key,
                    etag=etag,
                    status=AgentFile.Status.READY,
                    text=document.text,
                    text_truncated=document.truncated,
                    page_count=document.page_count,
                    pages_without_text=document.pages_without_text,
                )
        except Exception:
            self.storage.delete(key)
            raise

    @staticmethod
    def _scope(conversation: AgentConversation):
        return AgentFile.objects.defer("text").filter(
            conversation=conversation,
            source__in=WEB_SOURCES,
            status=AgentFile.Status.READY,
        )

    @staticmethod
    def _log(path: str, host, started: float, reason: str = "") -> None:
        # One line per fetch: how often the fallback serves is counted from these.
        logger.info(
            "web_fetch path=%s host=%s ms=%d reason=%s",
            path,
            host,
            (time.monotonic() - started) * 1000,
            re.sub(r"\s+", " ", reason) or "-",
        )
