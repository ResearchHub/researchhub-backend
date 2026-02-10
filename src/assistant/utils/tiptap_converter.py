"""
Converts Tiptap/ProseMirror JSON document structure to HTML.

Handles the standard node types used by the ResearchHub editor:
headings, paragraphs, lists, tables, blockquotes, code blocks,
and inline marks (bold, italic, links, etc.).
"""

import json
from html import escape


def tiptap_json_to_html(doc) -> str:
    """
    Convert a Tiptap JSON document to HTML.

    Args:
        doc: Either a dict (parsed JSON) or a JSON string.

    Returns:
        HTML string, or empty string if conversion fails.
    """
    if isinstance(doc, str):
        try:
            doc = json.loads(doc)
        except (json.JSONDecodeError, TypeError):
            return ""

    if not isinstance(doc, dict):
        return ""

    content = doc.get("content", [])
    return _render_nodes(content)


def _render_nodes(nodes: list) -> str:
    """Render a list of nodes to HTML."""
    return "".join(_render_node(node) for node in nodes)


def _render_node(node: dict) -> str:
    """Render a single node to HTML."""
    node_type = node.get("type", "")
    attrs = node.get("attrs", {})
    content = node.get("content", [])
    marks = node.get("marks", [])

    # Text node
    if node_type == "text":
        text = escape(node.get("text", ""))
        return _apply_marks(text, marks)

    # Hard break
    if node_type == "hardBreak":
        return "<br>"

    # Horizontal rule
    if node_type == "horizontalRule":
        return "<hr>"

    inner = _render_nodes(content)

    # Headings
    if node_type == "heading":
        level = attrs.get("level", 2)
        return f"<h{level}>{inner}</h{level}>"

    # Paragraph
    if node_type == "paragraph":
        return f"<p>{inner}</p>"

    # Lists
    if node_type == "bulletList":
        return f"<ul>{inner}</ul>"

    if node_type == "orderedList":
        start = attrs.get("start", 1)
        if start != 1:
            return f'<ol start="{start}">{inner}</ol>'
        return f"<ol>{inner}</ol>"

    if node_type == "listItem":
        return f"<li>{inner}</li>"

    # Blockquote
    if node_type == "blockquote":
        return f"<blockquote>{inner}</blockquote>"

    # Code block
    if node_type == "codeBlock":
        language = attrs.get("language", "")
        if language:
            return (
                f'<pre><code class="language-{escape(language)}">{inner}</code></pre>'
            )
        return f"<pre><code>{inner}</code></pre>"

    # Table
    if node_type == "table":
        return f"<table>{inner}</table>"

    if node_type == "tableRow":
        return f"<tr>{inner}</tr>"

    if node_type == "tableCell":
        colspan = attrs.get("colspan", 1)
        rowspan = attrs.get("rowspan", 1)
        attr_str = ""
        if colspan > 1:
            attr_str += f' colspan="{colspan}"'
        if rowspan > 1:
            attr_str += f' rowspan="{rowspan}"'
        return f"<td{attr_str}>{inner}</td>"

    if node_type == "tableHeader":
        colspan = attrs.get("colspan", 1)
        rowspan = attrs.get("rowspan", 1)
        attr_str = ""
        if colspan > 1:
            attr_str += f' colspan="{colspan}"'
        if rowspan > 1:
            attr_str += f' rowspan="{rowspan}"'
        return f"<th{attr_str}>{inner}</th>"

    # Image
    if node_type == "image":
        src = escape(attrs.get("src", ""))
        alt = escape(attrs.get("alt", ""))
        return f'<img src="{src}" alt="{alt}">'

    # Fallback: render content without wrapping tag
    return inner


def _apply_marks(text: str, marks: list) -> str:
    """Apply inline marks (bold, italic, link, etc.) to text."""
    for mark in marks:
        mark_type = mark.get("type", "")
        mark_attrs = mark.get("attrs", {})

        if mark_type == "bold":
            text = f"<strong>{text}</strong>"
        elif mark_type == "italic":
            text = f"<em>{text}</em>"
        elif mark_type == "strike":
            text = f"<s>{text}</s>"
        elif mark_type == "underline":
            text = f"<u>{text}</u>"
        elif mark_type == "code":
            text = f"<code>{text}</code>"
        elif mark_type == "link":
            href = escape(mark_attrs.get("href", ""))
            target = mark_attrs.get("target", "_blank")
            text = f'<a href="{href}" target="{target}">{text}</a>'
        elif mark_type == "subscript":
            text = f"<sub>{text}</sub>"
        elif mark_type == "superscript":
            text = f"<sup>{text}</sup>"

    return text
