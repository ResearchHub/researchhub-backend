"""
MIGRATION-ONLY: map legacy ``ExpertSearch.expert_results`` JSON rows to dicts for
``ExpertPersist.upsert_from_parsed_dict``. Remove this module when v1 expert
finder and ``expert_results`` storage are deleted (see strangler plan PR9).

Legacy v1 rows (markdown table pipeline) use keys: ``name``, ``title``,
``affiliation``, ``expertise``, ``email``, ``notes``, ``sources``. Structured
name fields are absent; ``title`` maps to ``Expert.academic_title``.

**Name splitting (heuristic, backfill-only):** There is no reliable inverse of
a free-form ``name`` string. This code applies small, deterministic rules so
rows are *mostly* usable for display and dedupe by email:

- Strip a short trailing segment after the last comma when it looks like a
  credential suffix (e.g. ``", PhD"``, ``", M.D."``).
- Strip a leading honorific token when it matches a small allowlist
  (Dr., Prof., Professor, Mr./Ms./Mrs., etc.).
- If the remainder contains a comma, treat it as ``Last, First [Middle]``:
  everything before the first comma is ``last_name``; after the comma, first
  token is ``first_name``, rest is ``middle_name``.
- Otherwise split on whitespace: one token → ``last_name`` only; two →
  ``first_name``, ``last_name``; three → ``first``, ``middle``, ``last``;
  four or more → ``first``, ``middle`` = middle tokens joined, ``last`` = last
  token.

Wrong splits are acceptable for a one-time backfill; operators can fix
individual ``Expert`` rows afterward. Rows already containing structured keys
(``first_name``, ``last_name``, ``honorific``, ``academic_title``) are merged
with legacy keys so partially filled JSON still migrates.
"""

from __future__ import annotations

import re
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from research_ai.services.expert_display import ExpertDisplay
from research_ai.services.expert_finder_json import ExpertFinderJson
from research_ai.utils import trimmed_str

# Leading tokens treated as honorific (comparison is case-insensitive, period optional).
_HONORIFIC_PREFIXES: frozenset[str] = frozenset(
    {
        "dr",
        "prof",
        "professor",
        "mr",
        "mrs",
        "ms",
        "miss",
        "sir",
        "dame",
    }
)

_SUFFIX_AFTER_COMMA = re.compile(
    r"^(ph\.?d\.?|m\.?d\.?|d\.?d\.?s\.?|jr\.?|sr\.?|ii|iii|iv|esq\.?)$",
    re.IGNORECASE,
)


def _token_key(t: str) -> str:
    return t.strip().rstrip(".").lower()


def _strip_trailing_comma_suffix(display: str) -> tuple[str, str]:
    """If ``display`` ends with ``, <short suffix>``, drop suffix for name parsing."""
    display = display.strip()
    if "," not in display:
        return display, ""
    left, right = display.rsplit(",", 1)
    right_stripped = right.strip()
    if not right_stripped or len(right_stripped) > 32 or " " in right_stripped:
        return display, ""
    if _SUFFIX_AFTER_COMMA.match(right_stripped):
        return left.strip(), right_stripped
    return display, ""


def _strip_leading_honorific(tokens: list[str]) -> tuple[str, list[str]]:
    honorific = ""
    if not tokens:
        return honorific, tokens
    key = _token_key(tokens[0])
    if key in _HONORIFIC_PREFIXES:
        honorific = tokens[0]
        return honorific, tokens[1:]
    return honorific, tokens


def _split_core_name_tokens(tokens: list[str]) -> tuple[str, str, str]:
    """Return first_name, middle_name, last_name from whitespace tokens."""
    if not tokens:
        return "", "", ""
    core = " ".join(tokens).strip()
    if "," in core:
        left, right = core.split(",", 1)
        last_chunk = left.strip()
        right_tokens = right.split()
        if last_chunk and right_tokens:
            return (
                right_tokens[0],
                " ".join(right_tokens[1:]).strip(),
                last_chunk,
            )
    n = len(tokens)
    if n == 1:
        return "", "", tokens[0]
    if n == 2:
        return tokens[0], "", tokens[1]
    if n == 3:
        return tokens[0], tokens[1], tokens[2]
    return tokens[0], " ".join(tokens[1:-1]), tokens[-1]


def split_legacy_display_name_for_migration(display_name: str) -> dict[str, str]:
    """
    Best-effort structured name fields from a legacy ``name`` string.

    See module docstring for limitations. Intended only for backfill.
    """
    body, comma_suffix = _strip_trailing_comma_suffix((display_name or "").strip())
    honorific, tokens = _strip_leading_honorific(body.split())
    first, middle, last = _split_core_name_tokens(tokens)
    name_suffix = comma_suffix
    return {
        "honorific": honorific,
        "first_name": first,
        "middle_name": middle,
        "last_name": last,
        "name_suffix": name_suffix,
    }


def _email_ok(email: str) -> bool:
    if not email:
        return False
    try:
        validate_email(email)
    except ValidationError:
        return False
    return True


def legacy_expert_result_row_to_parsed_dict(row: Any) -> dict[str, Any] | None:
    """
    Convert one legacy ``expert_results`` element to a dict for
    ``ExpertPersist.upsert_from_parsed_dict``.

    Returns ``None`` if the row is unusable (not a dict, missing/invalid email).
    """
    if not isinstance(row, dict):
        return None

    email = ExpertDisplay.normalize_email(trimmed_str(row.get("email", "")))
    if not email or not _email_ok(email):
        return None

    has_structured = any(
        trimmed_str(row.get(k, ""))
        for k in ("first_name", "last_name", "honorific", "academic_title")
    )

    parsed_from_name = split_legacy_display_name_for_migration(
        trimmed_str(row.get("name", ""))
    )

    if has_structured:
        parts = {
            "honorific": trimmed_str(row.get("honorific", ""), max_len=64)
            or parsed_from_name["honorific"],
            "first_name": trimmed_str(row.get("first_name", ""), max_len=255)
            or parsed_from_name["first_name"],
            "middle_name": trimmed_str(row.get("middle_name", ""), max_len=255)
            or parsed_from_name["middle_name"],
            "last_name": trimmed_str(row.get("last_name", ""), max_len=255)
            or parsed_from_name["last_name"],
            "name_suffix": trimmed_str(row.get("name_suffix", ""), max_len=64)
            or parsed_from_name["name_suffix"],
        }
    else:
        parts = parsed_from_name

    academic = trimmed_str(row.get("academic_title", ""), max_len=255)
    if not academic:
        academic = trimmed_str(row.get("title", ""), max_len=255)

    return {
        "email": email,
        "honorific": parts["honorific"],
        "first_name": parts["first_name"],
        "middle_name": parts["middle_name"],
        "last_name": parts["last_name"],
        "name_suffix": parts["name_suffix"],
        "academic_title": academic,
        "affiliation": trimmed_str(row.get("affiliation", "")),
        "expertise": trimmed_str(row.get("expertise", "")),
        "notes": trimmed_str(row.get("notes", "")),
        "sources": ExpertFinderJson.normalize_sources(row.get("sources")),
    }


def legacy_expert_results_to_persist_rows(
    expert_results: Any,
) -> list[dict[str, Any]]:
    """
    Map ``ExpertSearch.expert_results`` (legacy JSON list) to ordered, de-duplicated
    rows for ``ExpertPersist.replace_search_experts_for_search``. First row wins
    per normalized email.
    """
    if not isinstance(expert_results, list):
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in expert_results:
        parsed = legacy_expert_result_row_to_parsed_dict(item)
        if parsed is None:
            continue
        em = parsed["email"]
        if em in seen:
            continue
        seen.add(em)
        out.append(parsed)
    return out
