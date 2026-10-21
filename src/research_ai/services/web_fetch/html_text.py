"""A fetched HTML page as Markdown, links and image sources made absolute."""

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
# An image declared smaller on a side is an icon, spacer or tracking pixel.
_MIN_IMAGE_EDGE_PX = 32
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
        # Figures are often laid out in tables; anywhere else inline, an image is
        # reduced to its alt text.
        super().__init__(heading_style="ATX", keep_inline_images_in=["td", "th"])


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
    _absolutize_links(soup, base_url)
    _keep_images(soup, base_url)
    root = _content_root(soup)
    text = _Converter().convert_soup(root)
    return title, _BLANK_LINES.sub("\n\n", text).strip()


def _absolutize_links(soup, base_url: str) -> None:
    for link in soup.find_all("a", href=True):
        try:
            link["href"] = urljoin(base_url, link["href"])
        except ValueError:
            # A malformed destination, e.g. "http://[": keep the link's text only.
            del link["href"]
        # Rendered into every Markdown link, where it only repeats the text.
        del link["title"]


def _keep_images(soup, base_url: str) -> None:
    """Drops images with no web source or a tiny declared size; keeps src and alt."""
    for image in soup.find_all("img"):
        source = _image_source(image, base_url)
        if source is None or _declared_tiny(image):
            image.decompose()
        else:
            image.attrs = {"src": source, "alt": " ".join(image.get("alt", "").split())}


def _content_root(soup):
    root = soup.body or soup
    root_length = len(root.get_text())
    for name in ("main", "article"):
        element = soup.find(name)
        # A small one is a fragment of the page, not its content.
        if element is not None and len(element.get_text()) * 2 >= root_length:
            return element
    return root


def _image_source(image, base_url: str) -> str | None:
    """The image's absolute web URL: for a lazy-loaded one, its real source."""
    for name in ("data-src", "src"):
        value = image.get(name)
        if not isinstance(value, str) or value.strip().lower().startswith("data:"):
            continue
        try:
            source = urljoin(base_url, value.strip())
        except ValueError:
            continue
        if urlsplit(source).scheme in ("http", "https"):
            return source
    return None


def _declared_tiny(image) -> bool:
    for name in ("width", "height"):
        value = str(image.get(name, "")).strip().removesuffix("px")
        if value.isdigit() and int(value) < _MIN_IMAGE_EDGE_PX:
            return True
    return False


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
