import logging
import re
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator

from research_ai.services.expert_display import build_expert_display_name

logger = logging.getLogger(__name__)

_EMAIL_VALIDATOR = EmailValidator()

# NBSP and other unicode spaces often appear in model/web "email protected" placeholders.
_UNICODE_SPACE_CHARS_RE = re.compile(
    r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000\ufeff]+"
)


def _normalize_email_candidate(raw: str) -> str:
    """
    Strip and remove unicode whitespace from the email cell so values like
    ``jane.doe\\u00a0@mit.edu`` validate; does not fix non-email placeholders.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    s = _UNICODE_SPACE_CHARS_RE.sub("", s)
    return s.strip()


# Must match expert_finder_system.txt (build_system_prompt injects these lines).
EXPERT_LLM_TABLE_HEADERS: tuple[str, ...] = (
    "Honorific",
    "First name",
    "Middle name",
    "Last name",
    "Suffix",
    "Academic title",
    "Affiliation",
    "Expertise",
    "Email",
    "Notes",
)

N_EXPERT_COLUMNS = len(EXPERT_LLM_TABLE_HEADERS)

EXPERT_LLM_TABLE_HEADER_LINE = "| " + " | ".join(EXPERT_LLM_TABLE_HEADERS) + " |"
EXPERT_LLM_TABLE_SEPARATOR_LINE = "| " + " | ".join(["---"] * N_EXPERT_COLUMNS) + " |"


class ExpertTableSchemaError(ValueError):
    """Table header row does not match the required schema."""


class ExpertTableRowError(ValueError):
    """Reserved for row-level issues; the table parser skips bad rows instead of raising."""


def _is_markdown_separator_row(line: str) -> bool:
    """
    True for a markdown table separator row (cells are only --- / :--- / etc.).

    Must not match data rows whose first column is empty (e.g. '| | Jane | ...').
    """
    cells = _split_table_row(line)
    if len(cells) < 2:
        return False
    for c in cells:
        t = c.strip()
        if not t:
            return False
        if not re.fullmatch(r":?-{3,}:?", t):
            return False
    return True


def _normalize_header_label(s: str) -> str:
    return " ".join(s.strip().split())


def _headers_match(parsed: list[str]) -> bool:
    if len(parsed) != N_EXPERT_COLUMNS:
        return False
    for got, want in zip(parsed, EXPERT_LLM_TABLE_HEADERS):
        if _normalize_header_label(got).casefold() != want.casefold():
            return False
    return True


def _split_table_row(line: str) -> list[str]:
    """Split a markdown table data/header line into cells; preserve empty cells."""
    raw = line.strip()
    if not raw:
        return []
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|"):
        raw = raw[:-1]
    return [c.strip() for c in raw.split("|")]


def _collect_markdown_table_lines(markdown_text: str) -> list[str]:
    lines = markdown_text.split("\n")
    table_lines: list[str] = []
    in_table = False
    for line in lines:
        if "|" in line:
            if _is_markdown_separator_row(line):
                continue
            table_lines.append(line)
            in_table = True
        elif in_table and line.strip() == "":
            break
    return table_lines


def clean_expert_table_url(url: str) -> str:
    if "?" not in url:
        return url
    base, qs = url.split("?", 1)
    params = [p for p in qs.split("&") if not p.startswith("utm_")]
    return f"{base}?{'&'.join(params)}" if params else base


def extract_citations_from_notes(text: str) -> tuple[str, list[dict[str, str]]]:
    """Extract markdown links [text](url) from notes; return (cleaned_text, citations)."""
    citations: list[dict[str, str]] = []
    citation_pattern = r"\[([^\]]+)\]\(([^)]*)\)"
    for m in re.finditer(citation_pattern, text):
        raw_url = (m.group(2) or "").strip()
        if not raw_url:
            continue
        url = clean_expert_table_url(raw_url)
        citations.append({"text": m.group(1), "url": url})
    cleaned = re.sub(citation_pattern, "", text)
    cleaned = cleaned.replace("()", "").strip()
    return cleaned, citations


def parse_expert_markdown_table_strict(markdown_text: str) -> list[dict[str, Any]]:
    """
    Parse LLM markdown into expert dicts.

    - No table or only a header (no data rows): returns [].
    - Header row present but wrong columns/order: ExpertTableSchemaError (fails the
      whole parse; caller should treat as a bad model response).
    - Data rows: wrong column count, missing names, invalid email, or any unexpected
      error while building the row are skipped with a log line; valid rows are still
      returned.
    """
    table_lines = _collect_markdown_table_lines(markdown_text)
    if len(table_lines) < 2:
        return []

    header_cells = _split_table_row(table_lines[0])
    if not _headers_match(header_cells):
        raise ExpertTableSchemaError(
            "Expert table header row does not match the required columns and order. "
            f"Expected {N_EXPERT_COLUMNS} columns: {', '.join(EXPERT_LLM_TABLE_HEADERS)}."
        )

    experts: list[dict[str, Any]] = []
    for line_idx, line in enumerate(table_lines[1:], start=2):
        cells = _split_table_row(line)
        if not any(c.strip() for c in cells):
            continue
        if len(cells) != N_EXPERT_COLUMNS:
            logger.warning(
                "Skipping expert table row %s: expected %s columns, got %s",
                line_idx,
                N_EXPERT_COLUMNS,
                len(cells),
            )
            continue

        honorific = cells[0]
        first_name = cells[1]
        middle_name = cells[2]
        last_name = cells[3]
        name_suffix = cells[4]
        academic_title = cells[5]
        affiliation = cells[6]
        expertise = cells[7]
        email = cells[8]
        notes_raw = cells[9]

        if not (first_name or "").strip() or not (last_name or "").strip():
            logger.warning(
                "Skipping expert table row %s: first and last name are required",
                line_idx,
            )
            continue

        email_stripped = _normalize_email_candidate(email)
        try:
            _EMAIL_VALIDATOR(email_stripped)
        except ValidationError as e:
            detail = (
                e.messages[0]
                if getattr(e, "messages", None)
                else (str(e) or "invalid email")
            )
            logger.warning(
                "Skipping expert table row %s: invalid email after normalize %r: %s",
                line_idx,
                email_stripped,
                detail,
            )
            continue

        try:
            notes_cleaned, citations = extract_citations_from_notes(notes_raw)
            display_name = build_expert_display_name(
                honorific=honorific,
                first_name=first_name,
                middle_name=middle_name,
                last_name=last_name,
                name_suffix=name_suffix,
                fallback_name="",
            )

            experts.append(
                {
                    "honorific": honorific,
                    "first_name": first_name,
                    "middle_name": middle_name,
                    "last_name": last_name,
                    "name_suffix": name_suffix,
                    "academic_title": academic_title,
                    "affiliation": affiliation,
                    "expertise": expertise,
                    "email": email_stripped,
                    "notes": notes_cleaned,
                    "sources": citations if citations else [],
                    "name": display_name,
                }
            )
        except Exception:
            logger.exception(
                "Skipping expert table row %s: unexpected error while parsing row",
                line_idx,
            )
            continue

    return experts
