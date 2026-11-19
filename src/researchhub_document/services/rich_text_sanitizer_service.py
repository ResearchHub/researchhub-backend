import html
import json
import re
from typing import Any
from urllib.parse import urlsplit

import nh3

LINK_SCHEMES = frozenset({"http", "https", "mailto"})
MEDIA_SCHEMES = frozenset({"http", "https"})

_YOUTUBE_EMBED_HOSTS = frozenset(
    {"www.youtube.com", "youtube.com", "www.youtube-nocookie.com"}
)
_URL_SCHEME = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*):")
_URL_IGNORED_CHARACTERS = re.compile(r"[\t\n\r]")
_URL_LEADING_CHARACTERS = "".join(chr(code) for code in range(0x21))
_INLINE_IMAGE = re.compile(r"data:image/(?:png|jpe?g|gif|webp)[;,]", re.IGNORECASE)
_SAFE_CSS_VALUE = re.compile(r"[\w\s#%.,()+\-/'\"!]*")
_UNSAFE_CSS_FUNCTIONS = ("url(", "expression(", "image-set(", "image(", "src(")
_IFRAME_CONTENT = re.compile(
    r"""(<iframe(?:\s[^\s=>]+(?:="[^"]*")?)*>).*?(</iframe>)""", re.DOTALL
)

_EDITOR_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "col",
    "colgroup",
    "details",
    "div",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "iframe",
    "img",
    "input",
    "label",
    "li",
    "mark",
    "ol",
    "p",
    "pre",
    "s",
    "span",
    "strong",
    "sub",
    "summary",
    "sup",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}
_LEGACY_TAGS = {
    "abbr",
    "address",
    "article",
    "aside",
    "b",
    "bdi",
    "bdo",
    "caption",
    "cite",
    "data",
    "dd",
    "del",
    "dfn",
    "dl",
    "dt",
    "footer",
    "header",
    "hgroup",
    "i",
    "ins",
    "kbd",
    "main",
    "nav",
    "oembed",
    "q",
    "rb",
    "rp",
    "rt",
    "rtc",
    "ruby",
    "samp",
    "section",
    "small",
    "source",
    "strike",
    "tfoot",
    "time",
    "var",
    "video",
    "wbr",
}
_REMOVED_WITH_CONTENT_TAGS = {
    "applet",
    "base",
    "embed",
    "frame",
    "frameset",
    "head",
    "link",
    "math",
    "meta",
    "noembed",
    "noframes",
    "noscript",
    "object",
    "plaintext",
    "script",
    "style",
    "svg",
    "template",
    "title",
    "xmp",
}
_CELL_ATTRIBUTES = {
    "align",
    "colspan",
    "colwidth",
    "headers",
    "height",
    "rowspan",
    "scope",
    "valign",
    "width",
}
_ROW_ATTRIBUTES = {"align", "valign"}
_HEADING_ATTRIBUTES = {"id"}
_ALLOWED_ATTRIBUTES = {
    "*": {
        "class",
        "data-align",
        "data-checked",
        "data-color",
        "data-id",
        "data-latex",
        "data-name",
        "data-position",
        "data-toc-id",
        "data-type",
        "data-width",
        "data-youtube-video",
        "dir",
        "lang",
        "style",
        "title",
    },
    "a": {"href", "rel", "target"},
    "blockquote": {"cite"},
    "col": {"align", "span", "valign", "width"},
    "colgroup": {"align", "span", "valign", "width"},
    "data": {"value"},
    "del": {"cite", "datetime"},
    "details": {"open"},
    "figure": {"data-original-content"},
    "h1": _HEADING_ATTRIBUTES,
    "h2": _HEADING_ATTRIBUTES,
    "h3": _HEADING_ATTRIBUTES,
    "h4": _HEADING_ATTRIBUTES,
    "h5": _HEADING_ATTRIBUTES,
    "h6": _HEADING_ATTRIBUTES,
    "iframe": {
        "allowfullscreen",
        "autoplay",
        "disablekbcontrols",
        "enableiframeapi",
        "endtime",
        "frameborder",
        "height",
        "ivloadpolicy",
        "loop",
        "modestbranding",
        "origin",
        "playlist",
        "rel",
        "src",
        "start",
        "width",
    },
    "img": {
        "align",
        "alt",
        "draggable",
        "height",
        "loading",
        "sizes",
        "src",
        "srcset",
        "width",
    },
    "input": {"checked", "disabled"},
    "ins": {"cite", "datetime"},
    "li": {"value"},
    "oembed": {"url"},
    "ol": {"reversed", "start", "type"},
    "q": {"cite"},
    "source": {"media", "sizes", "src", "srcset", "type"},
    "table": {"align", "border", "cellpadding", "cellspacing", "summary", "width"},
    "tbody": _ROW_ATTRIBUTES,
    "td": _CELL_ATTRIBUTES,
    "tfoot": _ROW_ATTRIBUTES,
    "th": _CELL_ATTRIBUTES,
    "thead": _ROW_ATTRIBUTES,
    "time": {"datetime"},
    "tr": _ROW_ATTRIBUTES,
    "ul": {"type"},
    "video": {
        "autoplay",
        "controls",
        "height",
        "loop",
        "muted",
        "poster",
        "src",
        "width",
    },
}
_ALLOWED_STYLE_PROPERTIES = frozenset(
    {
        "background-color",
        "border",
        "border-bottom",
        "border-collapse",
        "border-color",
        "border-left",
        "border-radius",
        "border-right",
        "border-spacing",
        "border-style",
        "border-top",
        "border-width",
        "clear",
        "color",
        "float",
        "font",
        "font-family",
        "font-size",
        "font-style",
        "font-variant",
        "font-weight",
        "height",
        "letter-spacing",
        "line-height",
        "list-style",
        "list-style-position",
        "list-style-type",
        "margin",
        "margin-bottom",
        "margin-left",
        "margin-right",
        "margin-top",
        "max-height",
        "max-width",
        "min-height",
        "min-width",
        "padding",
        "padding-bottom",
        "padding-left",
        "padding-right",
        "padding-top",
        "table-layout",
        "text-align",
        "text-decoration",
        "text-indent",
        "text-transform",
        "vertical-align",
        "white-space",
        "width",
        "word-break",
    }
)

_RAW_HTML_ATTRIBUTES = frozenset(
    {"dangerouslysetinnerhtml", "html", "innerhtml", "outerhtml", "srcdoc"}
)
_REMOVED_URL_ATTRIBUTES = frozenset({"href", "link"})
_BLANKED_URL_ATTRIBUTES = frozenset({"url"})
_MEDIA_URL_ATTRIBUTES = frozenset({"image", "poster", "src", "video"})
_CSS_VALUE_ATTRIBUTES = frozenset({"color", "fontfamily", "fontsize"})
_EDITOR_ATTRIBUTE_KEYS = frozenset({"attrs", "attributes", "insert"})


def sanitize_html(content: Any) -> Any:
    if not isinstance(content, str) or "<" not in content:
        return content
    return _clean_markup(_HTML_CLEANER, content)


def sanitize_editor_document(document: Any) -> Any:
    parsed = document
    try:
        if isinstance(document, str):
            parsed = json.loads(document)
        if not isinstance(parsed, dict | list):
            return sanitize_html(document)
        cleaned = _clean_json(parsed)
    except ValueError:
        return sanitize_html(document)
    except RecursionError:
        return None
    if cleaned == parsed:
        return document
    return json.dumps(cleaned) if isinstance(document, str) else cleaned


def is_allowed_url(url: Any, schemes: frozenset[str]) -> bool:
    if not isinstance(url, str):
        return False
    return _url_scheme(url) in schemes | {None}


def _clean_markup(cleaner: nh3.Cleaner, content: str) -> str:
    cleaned = cleaner.clean(content)
    if "<iframe" not in cleaned:
        return cleaned
    return _IFRAME_CONTENT.sub(r"\1\2", cleaned)


def _url_scheme(url: str) -> str | None:
    normalized = _URL_IGNORED_CHARACTERS.sub("", html.unescape(url))
    match = _URL_SCHEME.match(normalized.lstrip(_URL_LEADING_CHARACTERS))
    return match.group(1).lower() if match else None


def _is_allowed_image_url(url: Any) -> bool:
    if isinstance(url, str):
        compact = _URL_IGNORED_CHARACTERS.sub("", url).lstrip(_URL_LEADING_CHARACTERS)
        if _INLINE_IMAGE.match(compact):
            return True
    return is_allowed_url(url, MEDIA_SCHEMES)


def _is_youtube_embed(url: str) -> bool:
    try:
        parts = urlsplit(_URL_IGNORED_CHARACTERS.sub("", url).strip())
        hostname = parts.hostname
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and hostname in _YOUTUBE_EMBED_HOSTS
        and parts.path.startswith("/embed/")
        and ".." not in parts.path
    )


def _is_safe_css_value(value: Any) -> bool:
    if not isinstance(value, str) or not _SAFE_CSS_VALUE.fullmatch(value):
        return False
    lowered = value.lower()
    return not any(function in lowered for function in _UNSAFE_CSS_FUNCTIONS)


def _clean_style(style: str) -> str | None:
    declarations = [part for part in style.split(";") if part.strip()]
    allowed = []
    for declaration in declarations:
        name, separator, value = declaration.partition(":")
        if (
            separator
            and name.strip().lower() in _ALLOWED_STYLE_PROPERTIES
            and _is_safe_css_value(value)
        ):
            allowed.append(declaration)
    if not allowed:
        return None
    if len(allowed) == len(declarations):
        return style
    return "; ".join(part.strip() for part in allowed) + ";"


def _filter_html_attribute(tag: str, attribute: str, value: str) -> str | None:
    if attribute == "style":
        return _clean_style(value)
    if attribute == "data-original-content":
        return _clean_markup(_FIGURE_CONTENT_CLEANER, value)
    if attribute in ("href", "cite", "url"):
        allowed = is_allowed_url(value, LINK_SCHEMES)
    elif attribute == "poster":
        allowed = is_allowed_url(value, MEDIA_SCHEMES)
    elif attribute == "srcset":
        allowed = all(
            is_allowed_url(candidate.strip(), MEDIA_SCHEMES)
            for candidate in value.split(",")
        )
    elif attribute == "src" and tag == "iframe":
        allowed = _is_youtube_embed(value)
    elif attribute == "src" and tag == "img":
        allowed = _is_allowed_image_url(value)
    elif attribute == "src":
        allowed = is_allowed_url(value, MEDIA_SCHEMES)
    else:
        allowed = True
    return value if allowed else None


def _build_cleaner(attributes: dict[str, set[str]]) -> nh3.Cleaner:
    return nh3.Cleaner(
        tags=_EDITOR_TAGS | _LEGACY_TAGS,
        clean_content_tags=_REMOVED_WITH_CONTENT_TAGS,
        attributes=attributes,
        attribute_filter=_filter_html_attribute,
        link_rel=None,
        tag_attribute_values={"input": {"type": {"checkbox"}}},
        set_tag_attribute_values={"input": {"type": "checkbox"}},
        url_schemes=set(LINK_SCHEMES | {"data"}),
    )


_HTML_CLEANER = _build_cleaner(_ALLOWED_ATTRIBUTES)
_FIGURE_CONTENT_CLEANER = _build_cleaner(
    {tag: names for tag, names in _ALLOWED_ATTRIBUTES.items() if tag != "figure"}
)


def _clean_json(value: Any) -> Any:
    if isinstance(value, list):
        return [_clean_json(item) for item in value]
    if not isinstance(value, dict):
        return value
    cleaned = {}
    for key, item in value.items():
        if key == "marks" and isinstance(item, list):
            cleaned[key] = _clean_marks(item)
        elif key in _EDITOR_ATTRIBUTE_KEYS and isinstance(item, dict):
            cleaned[key] = _clean_editor_attributes(item)
        else:
            cleaned[key] = _clean_json(item)
    return cleaned


def _clean_marks(marks: list[Any]) -> list[Any]:
    return [_clean_json(mark) for mark in marks if not _is_unsafe_link_mark(mark)]


def _is_unsafe_link_mark(mark: Any) -> bool:
    if not isinstance(mark, dict) or mark.get("type") != "link":
        return False
    attributes = mark.get("attrs")
    href = attributes.get("href") if isinstance(attributes, dict) else None
    return href is not None and not is_allowed_url(href, LINK_SCHEMES)


def _clean_editor_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    cleaned = {}
    for name, value in attributes.items():
        lowered = name.lower()
        if lowered.startswith("on") or lowered in _RAW_HTML_ATTRIBUTES:
            continue
        if value is None:
            cleaned[name] = value
        elif lowered == "originalcontent":
            is_markup = isinstance(value, str)
            cleaned[name] = (
                _clean_markup(_FIGURE_CONTENT_CLEANER, value) if is_markup else ""
            )
        elif lowered in _REMOVED_URL_ATTRIBUTES:
            if is_allowed_url(value, LINK_SCHEMES):
                cleaned[name] = value
        elif lowered in _BLANKED_URL_ATTRIBUTES:
            cleaned[name] = value if is_allowed_url(value, LINK_SCHEMES) else ""
        elif lowered in _MEDIA_URL_ATTRIBUTES:
            cleaned[name] = value if _is_allowed_image_url(value) else ""
        elif lowered == "style":
            style = _clean_style(value) if isinstance(value, str) else None
            if style is not None:
                cleaned[name] = style
        elif lowered in _CSS_VALUE_ATTRIBUTES:
            if _is_safe_css_value(value):
                cleaned[name] = value
        else:
            cleaned[name] = value
    return cleaned
