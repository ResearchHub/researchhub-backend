import json
from contextlib import suppress

from django.utils.html import escape, format_html, linebreaks
from django.utils.safestring import SafeString, mark_safe

from mailing_list.services import truncate_preview
from researchhub_comment.constants.rh_comment_content_types import TIPTAP
from researchhub_comment.models import RhCommentModel

_NODE_TAGS = {
    "blockquote": "blockquote",
    "bulletList": "ul",
    "codeBlock": "pre",
    "listItem": "li",
    "orderedList": "ol",
    "paragraph": "p",
}
_MARK_TAGS = {
    "bold": "strong",
    "code": "code",
    "italic": "em",
    "strike": "s",
    "underline": "u",
}
_ALLOWED_LINK_SCHEME = "https://"


def render_comment_html(
    comment: RhCommentModel, max_length: int | None = None
) -> SafeString:
    """Render a comment body as escaped HTML for email, without images.

    With `max_length`, stop after that many characters of text and end with an
    ellipsis. Malformed Tiptap content falls back to the comment's plain text.
    """
    if comment.comment_content_type == TIPTAP:
        content = comment.comment_content_json
        with suppress(AttributeError, KeyError, TypeError, ValueError):
            document = json.loads(content) if isinstance(content, str) else content
            return _TiptapRenderer(max_length).render(document.get("content", []))
    text = comment.plain_text
    if max_length is not None:
        text = truncate_preview(text, max_length)
    return mark_safe(linebreaks(text, autoescape=True))


class _TiptapRenderer:
    """Render Tiptap nodes, spending a shared character budget on their text."""

    def __init__(self, max_length: int | None) -> None:
        self._remaining = max_length
        self._truncated = False

    def render(self, nodes: list[dict]) -> SafeString:
        """Render sibling nodes in order, stopping once the budget runs out."""
        html = []
        for node in nodes:
            if self._truncated:
                break
            html.append(self._render_node(node))
        return mark_safe("".join(html))

    def _render_node(self, node: dict) -> SafeString:
        """Render one node, keeping only the children of nodes email cannot show."""
        node_type = node["type"]
        if node_type == "text":
            return self._render_text(node)

        attrs = node.get("attrs", {})
        if node_type == "mention":
            return escape(self._spend(attrs.get("displayName") or attrs["label"]))
        if node_type == "richLink":
            url = attrs["url"]
            text = self._spend(url)
            if url.lower().startswith(_ALLOWED_LINK_SCHEME):
                return format_html('<a href="{}">{}</a>', url, text)
            return escape(text)
        if node_type == "inlineMath":
            return escape(self._spend(attrs.get("latex", "")))
        if node_type == "blockMath":
            return format_html("<p>{}</p>", self._spend(attrs.get("latex", "")))
        if node_type == "hardBreak":
            return mark_safe("<br>")
        if node_type == "horizontalRule":
            return mark_safe("<hr>")

        children = self.render(node.get("content", []))
        if node_type in _NODE_TAGS:
            return format_html("<{0}>{1}</{0}>", _NODE_TAGS[node_type], children)
        if node_type == "heading":
            return format_html("<h{0}>{1}</h{0}>", int(attrs["level"]), children)
        return children

    def _render_text(self, node: dict) -> SafeString:
        """Render a text node wrapped in each of its marks."""
        html = escape(self._spend(node["text"]))
        for mark in node.get("marks", []):
            if mark["type"] == "link":
                href = mark["attrs"]["href"]
                if href.lower().startswith(_ALLOWED_LINK_SCHEME):
                    html = format_html('<a href="{}">{}</a>', href, html)
            else:
                html = format_html("<{0}>{1}</{0}>", _MARK_TAGS[mark["type"]], html)
        return html

    def _spend(self, text: str) -> str:
        """Return as much of the text as the budget allows, ellipsized if cut."""
        if self._remaining is None:
            return text
        if len(text) > self._remaining:
            self._truncated = True
            return truncate_preview(text, self._remaining)
        self._remaining -= len(text)
        return text
