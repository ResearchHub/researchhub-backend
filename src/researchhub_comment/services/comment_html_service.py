import json

from django.utils.html import escape, format_html
from django.utils.safestring import SafeString, mark_safe

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


def render_comment_html(content: dict | str) -> SafeString:
    """Render stored TipTap comment content as escaped HTML for email."""
    document = json.loads(content) if isinstance(content, str) else content
    return _render_nodes(document.get("content", []))


def _render_nodes(nodes: list[dict]) -> SafeString:
    """Render sibling nodes in order."""
    return mark_safe("".join(_render_node(node) for node in nodes))


def _render_node(node: dict) -> SafeString:
    """Render one node, keeping only the children of nodes email cannot show."""
    node_type = node["type"]
    if node_type == "text":
        return _render_text(node)

    attrs = node.get("attrs", {})
    children = _render_nodes(node.get("content", []))
    if node_type in _NODE_TAGS:
        return format_html("<{0}>{1}</{0}>", _NODE_TAGS[node_type], children)
    if node_type == "heading":
        return format_html("<h{0}>{1}</h{0}>", attrs["level"], children)
    if node_type == "hardBreak":
        return mark_safe("<br>")
    if node_type == "horizontalRule":
        return mark_safe("<hr>")
    if node_type == "image":
        return format_html(
            '<img src="{}" alt="{}">', attrs["src"], attrs.get("alt") or ""
        )
    if node_type == "mention":
        return escape(attrs.get("displayName") or attrs["label"])
    if node_type == "richLink":
        return format_html('<a href="{0}">{0}</a>', attrs["url"])
    return children


def _render_text(node: dict) -> SafeString:
    """Render a text node wrapped in each of its marks."""
    html = escape(node["text"])
    for mark in node.get("marks", []):
        if mark["type"] == "link":
            html = format_html('<a href="{}">{}</a>', mark["attrs"]["href"], html)
        else:
            html = format_html("<{0}>{1}</{0}>", _MARK_TAGS[mark["type"]], html)
    return html
