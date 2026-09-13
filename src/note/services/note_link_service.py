"""Make plain-text source URLs clickable in blocks written by note agents."""

from linkify_it import LinkifyIt


def link_note_urls(blocks: list[dict]) -> list[dict]:
    """Add ProseMirror links to HTTP(S) URLs in inserted/replaced blocks.

    Preserve existing links, formatting, code, and all visible text. This is
    URL detection only; the document is not parsed as Markdown. Use a detector
    per operation because LinkifyIt keeps mutable match state.
    """
    detector = LinkifyIt(
        schemas={"ftp:": None, "mailto:": None, "//": None},
        options={"fuzzy_link": False, "fuzzy_email": False, "fuzzy_ip": False},
    )
    return _link_nodes(blocks, detector)


def _link_nodes(blocks: list[dict], detector: LinkifyIt) -> list[dict]:
    result = []
    for node in blocks:
        marks = node.get("marks", [])
        if node.get("type") == "codeBlock" or any(
            mark["type"] in ("code", "link") for mark in marks
        ):
            result.append(node)
        elif node.get("type") == "text":
            result.extend(_link_text(node, detector))
        elif "content" in node:
            result.append({**node, "content": _link_nodes(node["content"], detector)})
        else:
            result.append(node)
    return result


def _link_text(node: dict, detector: LinkifyIt) -> list[dict]:
    text = node["text"]
    if "http" not in text.lower():
        return [node]
    result = []
    cursor = 0
    for match in detector.match(text) or []:
        if match.index > cursor:
            result.append({**node, "text": text[cursor : match.index]})
        result.append(
            {
                **node,
                "text": match.raw,
                "marks": [
                    *node.get("marks", []),
                    {"type": "link", "attrs": {"href": match.url}},
                ],
            }
        )
        cursor = match.last_index
    if cursor < len(text):
        result.append({**node, "text": text[cursor:]})
    return result
