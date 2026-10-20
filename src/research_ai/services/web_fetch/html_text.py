"""A fetched HTML page as Markdown, links made absolute."""

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

from research_ai.services.web_fetch.scope import valid_host

_DROPPED_TAGS = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "iframe",
    "form",
    "button",
    "nav",
    "footer",
)
_BLANK_LINES = re.compile(r"\n{3,}")
# Markers of a bot-detection interstitial (Cloudflare, DataDome, Imperva, AWS WAF).
_CHALLENGE_MARKERS = (
    "cf-chl-",
    "challenge-platform",
    "just a moment...",
    "captcha-delivery.com",
    "_incapsula_resource",
    "awswaf",
    "enable javascript and cookies to continue",
)


class _Converter(MarkdownConverter):
    def __init__(self):
        super().__init__(heading_style="ATX", strip=["img"])


def looks_like_challenge(data: bytes) -> bool:
    head = data[:20_000].decode("utf-8", "ignore").lower()
    return any(marker in head for marker in _CHALLENGE_MARKERS)


def html_to_markdown(
    data: bytes, *, base_url: str, encoding: str | None
) -> tuple[str, str]:
    """The page's ``(title, markdown)``: its main content where marked up as such."""
    soup = BeautifulSoup(data, "lxml", from_encoding=encoding)
    title = " ".join(soup.title.get_text().split()) if soup.title else ""
    for tag in soup(_DROPPED_TAGS):
        tag.decompose()
    base = soup.find("base", href=True)
    if base is not None:
        base_url = _document_base(base_url, base["href"])
    for link in soup.find_all("a", href=True):
        try:
            link["href"] = urljoin(base_url, link["href"])
        except ValueError:
            # A malformed destination, e.g. "http://[": keep the link's text only.
            del link["href"]
        # Rendered into every Markdown link, where it only repeats the text.
        del link["title"]
    root = soup.body or soup
    root_length = len(root.get_text())
    for name in ("main", "article"):
        element = soup.find(name)
        if element is None:
            continue
        # A small one is a fragment of the page, not its content.
        if len(element.get_text()) * 2 >= root_length:
            root = element
            break
    text = _Converter().convert_soup(root)
    return title, _BLANK_LINES.sub("\n\n", text).strip()


def _document_base(base_url: str, href: str) -> str:
    """Where the page's ``<base href>`` points relative links, if it is a web URL."""
    try:
        resolved = urljoin(base_url, href)
        parts = urlsplit(resolved)
        # Raises on a port that is not a number from 0 to 65535.
        port = parts.port
    except ValueError:
        return base_url
    if (
        parts.scheme in ("http", "https")
        and parts.hostname
        and valid_host(parts.hostname)
        and port != 0
    ):
        return resolved
    return base_url
