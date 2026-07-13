"""Assemble the readable proposal from the submitted sections.

The agent submits only the structured ``sections`` (plus ``citations``); the
server owns the two derived representations -- the readable ``plain_text`` and
the ProseMirror document -- so the model never re-emits the full proposal
several times over on every submit. The submit gate assembles the text this way
before scoring it with the judge panel and writing the accepted draft to a
``Note``.

The document is a numbered grant layout, and the numbering is owned here -- the
agent submits only the prose that fills each heading:

    1. Background and Hypothesis
    2. Research Strategy
       2.1 Preliminary Data and Rationale
       2.2 Specific Aims
           Specific Aim 1: <title>
           ...
    3. Investigator and Team Qualifications
    4. Budget and Timeline
       4.1 Budget Justification
       4.2 Timeline and Milestones
    5. References

An empty leaf section (or a container whose subsections are all empty) is
dropped rather than rendered as a bare heading, so a stub still fails the gate's
shape and length checks.
"""

import re

from research_ai.services.proposal_tools.doi import doi_url


def _split_paragraphs(text: object) -> list[str]:
    """Split a section body into paragraphs on blank lines."""
    return [
        part.strip() for part in re.split(r"\n\s*\n", str(text or "")) if part.strip()
    ]


def valid_aims(aims: object) -> list[dict]:
    """The submitted aims that carry both a title and a body, normalized.

    Shared with the sections gate so "which aims render" and "which aims count
    as present" cannot drift apart.
    """
    aims = aims if isinstance(aims, list) else []
    valid: list[dict] = []
    for aim in aims:
        if not isinstance(aim, dict):
            continue
        title = str(aim.get("title") or "").strip()
        body = str(aim.get("body") or "").strip()
        if title and body:
            valid.append({"title": title, "body": body})
    return valid


def _reference_line(citation: object) -> str:
    """One rendered reference: ``Authors (Year). Title. <doi-url>``.

    The year is rendered next to the authors -- when present -- so an inline
    author-year citation ("(Weber et al., 2025)") has a matching anchor in the
    list. Blank parts are dropped.
    """
    if not isinstance(citation, dict):
        return ""
    authors = citation.get("authors")
    authors = authors if isinstance(authors, list) else []
    author_text = ", ".join(a for a in (str(x).strip() for x in authors) if a)
    year = str(citation.get("year") or "").strip()
    if author_text and year:
        author_text = f"{author_text} ({year})"
    parts = [
        part
        for part in (
            author_text,
            str(citation.get("title") or "").strip(),
            doi_url(citation.get("doi")),
        )
        if part
    ]
    return ". ".join(parts)


class _DocBuilder:
    """Accumulates the ProseMirror content and the parallel plain-text parts."""

    def __init__(self):
        self.content: list[dict] = []
        self.text_parts: list[str] = []

    def heading(self, level: int, text: str) -> None:
        self.content.append(
            {
                "type": "heading",
                "attrs": {"level": level},
                "content": [{"type": "text", "text": text}],
            }
        )
        self.text_parts.append(text)

    def paragraph(self, text: str) -> None:
        self.content.append(
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        )
        self.text_parts.append(text)

    def body(self, text: object) -> None:
        """Emit one paragraph node per blank-line-separated paragraph."""
        for paragraph in _split_paragraphs(text):
            self.paragraph(paragraph)


def assemble_proposal(sections: object, citations: object = None) -> tuple[str, dict]:
    """Build ``(plain_text, prosemirror)`` from ``sections`` (and ``citations``).

    ``plain_text`` is the readable proposal -- the title, then each non-empty
    section under its numbered heading, then a References list built from the
    submitted citations. ``prosemirror`` is the matching document: an H1 title,
    H2 top-level sections, H3 subsections, an H4 per specific aim, and a
    paragraph node per blank-line-separated paragraph. Empty sections (and
    containers whose subsections are all empty) are skipped.
    """
    sections = sections if isinstance(sections, dict) else {}
    doc = _DocBuilder()

    title = str(sections.get("title") or "").strip()
    if title:
        doc.heading(1, title)

    # 1. Background and Hypothesis
    if _split_paragraphs(sections.get("background")):
        doc.heading(2, "1. Background and Hypothesis")
        doc.body(sections.get("background"))

    # 2. Research Strategy -- preliminary data + specific aims.
    prelim = _split_paragraphs(sections.get("preliminary_data"))
    aims = valid_aims(sections.get("aims"))
    if prelim or aims:
        doc.heading(2, "2. Research Strategy")
        if prelim:
            doc.heading(3, "2.1 Preliminary Data and Rationale")
            doc.body(sections.get("preliminary_data"))
        if aims:
            doc.heading(3, "2.2 Specific Aims")
            for index, aim in enumerate(aims, start=1):
                doc.heading(4, f"Specific Aim {index}: {aim['title']}")
                doc.body(aim["body"])

    # 3. Investigator and Team Qualifications
    if _split_paragraphs(sections.get("why_this_team")):
        doc.heading(2, "3. Investigator and Team Qualifications")
        doc.body(sections.get("why_this_team"))

    # 4. Budget and Timeline -- budget justification + timeline/milestones.
    budget = _split_paragraphs(sections.get("budget"))
    timeline = _split_paragraphs(sections.get("timeline"))
    if budget or timeline:
        doc.heading(2, "4. Budget and Timeline")
        if budget:
            doc.heading(3, "4.1 Budget Justification")
            doc.body(sections.get("budget"))
        if timeline:
            doc.heading(3, "4.2 Timeline and Milestones")
            doc.body(sections.get("timeline"))

    # 5. References -- rendered from the submitted, gate-grounded citations.
    citation_list = citations if isinstance(citations, list) else []
    references = [line for line in map(_reference_line, citation_list) if line]
    if references:
        doc.heading(2, "5. References")
        for index, line in enumerate(references, start=1):
            doc.paragraph(f"{index}. {line}")

    return "\n\n".join(doc.text_parts), {"type": "doc", "content": doc.content}
