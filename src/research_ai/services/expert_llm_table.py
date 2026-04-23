"""
Strict markdown table parsing for the expert-finder LLM: fixed 10-column header.
"""

import logging
import re
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator

logger = logging.getLogger(__name__)

# Must stay aligned with the expert-finder system prompt and parse_expert_markdown_table_strict.
EXPERT_LLM_TABLE_HEADERS: tuple[str, ...] = (
    "Honorific",
    "First",
    "Middle",
    "Last",
    "Suffix",
    "Academic title",
    "Affiliation",
    "Expertise",
    "Email",
    "Notes",
)

N_EXPERT_COLUMNS = len(EXPERT_LLM_TABLE_HEADERS)
EXPERT_LLM_TABLE_HEADER_LINE: str = (
    "| " + " | ".join(EXPERT_LLM_TABLE_HEADERS) + " |"
)
EXPERT_LLM_TABLE_SEPARATOR_LINE: str = (
    "| " + " | ".join("---" for _ in range(N_EXPERT_COLUMNS)) + " |"
)


class ExpertTableSchemaError(ValueError):
    """Raised when the model output is not a valid 10-column expert table."""


def clean_expert_table_url(url: str) -> str:
    """Remove UTM and tracking query params (same behavior as the legacy table parser)."""
    if "?" not in url:
        return url
    base, qs = url.split("?", 1)
    params = [p for p in qs.split("&") if not p.startswith("utm_")]
    return f"{base}?{'&'.join(params)}" if params else base


def extract_citations_from_notes(text: str) -> tuple[str, list[dict[str, str]]]:
    """
    Extract markdown links [text](url) from notes; return (cleaned_text, citations list).
    """
    citations: list[dict[str, str]] = []
    citation_pattern = r"\[([^\]]+)\]\(([^)]*)\)"
    for m in re.finditer(citation_pattern, text or ""):
        raw_url = (m.group(2) or "").strip()
        if not raw_url:
            continue
        url = clean_expert_table_url(raw_url)
        citations.append({"text": m.group(1), "url": url})
    cleaned = re.sub(citation_pattern, "", text or "")
    cleaned = re.sub(r"\(\)", "", cleaned).strip()
    return cleaned, citations


def _split_pipe_row(line: str) -> list[str]:
    s = (line or "").rstrip()
    if "|" not in s:
        return []
    parts = s.split("|")
    if len(parts) < 3:
        return []
    return [p.strip() for p in parts[1:-1]]


def _normalize_header_cell(s: str) -> str:
    return " ".join(s.split()).casefold()


def _is_markdown_alignment_separator_line(line: str) -> bool:
    """
    True for rows like | --- | --- |: alignment rows only, not | | A | (empty honorific + data).
    The legacy pattern ^\\s*\\|[\\s\\-:]+\\| matches a single space as \\s+ between pipes and wrongly
    drops any row whose first cell is empty.
    """
    cells = _split_pipe_row(line)
    if not cells:
        return False
    if not any("-" in c for c in cells):
        return False
    for c in cells:
        t = c.strip()
        if t == "":
            continue
        if not re.fullmatch(r"[-\s:]+", t):
            return False
    return True


def _row_is_table_separator(cells: list[str]) -> bool:
    if not cells:
        return True
    if not any("-" in c for c in cells):
        return False
    return all(
        c.strip() == "" or re.fullmatch(r"[-\s:]+", c) for c in cells
    )


def _table_lines_from_markdown(markdown_text: str) -> list[str]:
    """First contiguous run of | lines, skipping leading separator lines."""
    table_lines: list[str] = []
    in_table = False
    for line in (markdown_text or "").splitlines():
        if "|" in line:
            if _is_markdown_alignment_separator_line(line):
                continue
            table_lines.append(line)
            in_table = True
        elif in_table and not line.strip():
            break
    if not table_lines:
        return []
    return table_lines


def _header_matches(cells: list[str]) -> bool:
    if len(cells) != N_EXPERT_COLUMNS:
        return False
    for i, expected in enumerate(EXPERT_LLM_TABLE_HEADERS):
        got = cells[i]
        if _normalize_header_cell(got) != _normalize_header_cell(expected):
            return False
    return True


def parse_expert_markdown_table_strict(markdown_text: str) -> list[dict[str, Any]]:
    """
    Parse the expert markdown table into a list of expert dicts.
    Enforces 10 headers and 10 data cells per row. Skips data rows with invalid email.
    """
    table_lines = _table_lines_from_markdown(markdown_text)
    if not table_lines:
        raise ExpertTableSchemaError("No markdown table with pipe delimiters in response")

    header_cells = _split_pipe_row(table_lines[0])
    if not _header_matches(header_cells):
        raise ExpertTableSchemaError(
            "Invalid table header: expected "
            f"{N_EXPERT_COLUMNS} columns: {', '.join(EXPERT_LLM_TABLE_HEADERS)}"
        )

    out: list[dict[str, Any]] = []
    for line in table_lines[1:]:
        if not line or not line.strip():
            continue
        if "|" not in line:
            break
        row_cells = _split_pipe_row(line)
        if _row_is_table_separator(row_cells) or not any(c.strip() for c in row_cells):
            continue
        if len(row_cells) != N_EXPERT_COLUMNS:
            raise ExpertTableSchemaError(
                f"Table row has {len(row_cells)} cells; expected {N_EXPERT_COLUMNS}. "
                f"Row: {line[:200]!r}"
            )
        (
            honorific,
            first,
            middle,
            last,
            suffix,
            academic,
            affil,
            expertise,
            email_raw,
            notes_raw,
        ) = row_cells
        notes_clean, citations = extract_citations_from_notes(notes_raw)
        expert = {
            "honorific": honorific,
            "first_name": first,
            "middle_name": middle,
            "last_name": last,
            "name_suffix": suffix,
            "academic_title": academic,
            "affiliation": affil,
            "expertise": expertise,
            "email": (email_raw or "").strip().lower(),
            "notes": notes_clean,
            "sources": citations if citations else [],
        }
        try:
            EmailValidator()(expert["email"])
        except ValidationError:
            logger.warning(
                "Strict expert table: skipping row: invalid email %r",
                email_raw,
            )
            continue
        out.append(expert)
    return out
