"""Assemble the readable proposal from the submitted sections.

The agent submits only the structured ``sections`` (plus ``citations``); the
server owns the two derived representations -- the readable ``plain_text`` and
the ProseMirror document -- so the model never re-emits the full proposal three
times over (sections + prose + ProseMirror JSON) on every submit. The submit
gate assembles the text this way before scoring it with the judge panel and
writing the accepted draft to a ``Note``.
"""

import re

# Ordered body sections, each with the heading it renders under. ``title`` is
# the document's H1 and is handled separately.
PROPOSAL_SECTIONS = (
    ("hypothesis", "Hypothesis"),
    ("approach", "Approach"),
    ("why_this_team", "Why this team"),
    ("scope_timeline", "Scope & timeline"),
)


def _split_paragraphs(text: str) -> list[str]:
    """Split a section body into paragraphs on blank lines."""
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def assemble_proposal(sections: object) -> tuple[str, dict]:
    """Build ``(plain_text, prosemirror)`` from a submitted ``sections`` object.

    ``plain_text`` is the readable proposal -- the title, then each non-empty
    section under its heading. ``prosemirror`` is the matching document: an H1
    title, an H2 per section, and a paragraph node per blank-line-separated
    paragraph. Empty sections are skipped, so a stub still fails the gate's
    shape and length checks.
    """
    sections = sections if isinstance(sections, dict) else {}
    content: list[dict] = []
    text_parts: list[str] = []

    title = str(sections.get("title") or "").strip()
    if title:
        content.append(
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": title}],
            }
        )
        text_parts.append(title)

    for key, heading in PROPOSAL_SECTIONS:
        body = str(sections.get(key) or "").strip()
        if not body:
            continue
        content.append(
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": heading}],
            }
        )
        text_parts.append(heading)
        for paragraph in _split_paragraphs(body):
            content.append(
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": paragraph}],
                }
            )
            text_parts.append(paragraph)

    return "\n\n".join(text_parts), {"type": "doc", "content": content}
