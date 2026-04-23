"""
Display / API shaping helpers for Expert name fields and legacy dict rows.
"""

from typing import Any

from research_ai.models import Expert


def normalize_expert_email(email: str | None) -> str:
    """Lowercase, strip; empty string if missing or invalid type."""
    if not email or not isinstance(email, str):
        return ""
    return email.strip().lower()


def build_expert_display_name(
    *,
    honorific: str = "",
    first_name: str = "",
    middle_name: str = "",
    last_name: str = "",
    name_suffix: str = "",
) -> str:
    """
    One-line display from structured name parts (honorific through last), then suffix
    with a comma when both the base and suffix are non-empty (e.g. "Jane Smith, PhD").
    """
    parts: list[str] = []
    for s in (honorific, first_name, middle_name, last_name):
        t = (s or "").strip()
        if t:
            parts.append(t)
    base = " ".join(parts)
    suf = (name_suffix or "").strip()
    if base and suf:
        return f"{base}, {suf}"
    return base or suf


def expert_model_display_name(expert: Expert) -> str:
    return build_expert_display_name(
        honorific=expert.honorific,
        first_name=expert.first_name,
        middle_name=expert.middle_name,
        last_name=expert.last_name,
        name_suffix=expert.name_suffix,
    )


def expert_dict_to_api_payload(d: dict[str, Any] | None) -> dict[str, Any]:
    """
    Normalize a flat or legacy expert dict for list/detail API responses.
    Fills `name` from structured parts when any are present, else from legacy `name`.
    Synchronizes `academic_title` and legacy `title` (academic / role name).
    """
    if not d:
        return {}
    result: dict[str, Any] = {**d}
    any_structured = any(
        (result.get(k) or "").strip()
        for k in (
            "honorific",
            "first_name",
            "middle_name",
            "last_name",
            "name_suffix",
        )
    )
    if any_structured:
        result["name"] = build_expert_display_name(
            honorific=(result.get("honorific") or ""),
            first_name=(result.get("first_name") or ""),
            middle_name=(result.get("middle_name") or ""),
            last_name=(result.get("last_name") or ""),
            name_suffix=(result.get("name_suffix") or ""),
        )
    else:
        result["name"] = (result.get("name") or "").strip()

    at = (result.get("academic_title") or result.get("title") or "").strip()
    if not isinstance(at, str):
        at = ""
    result["academic_title"] = at
    result["title"] = at
    return result


def expert_name_for_generated_email_storage(
    expert_row: dict[str, Any] | None,
) -> str:
    """Single-line `GeneratedEmail.expert_name` from a structured or legacy row."""
    if not expert_row:
        return ""
    any_structured = any(
        (expert_row.get(k) or "").strip()
        for k in (
            "honorific",
            "first_name",
            "middle_name",
            "last_name",
            "name_suffix",
        )
    )
    if any_structured:
        return build_expert_display_name(
            honorific=(expert_row.get("honorific") or ""),
            first_name=(expert_row.get("first_name") or ""),
            middle_name=(expert_row.get("middle_name") or ""),
            last_name=(expert_row.get("last_name") or ""),
            name_suffix=(expert_row.get("name_suffix") or ""),
        )[:255]
    name = (expert_row.get("name") or "").strip()
    return name[:255]


def expert_title_for_generated_email_storage(
    expert_row: dict[str, Any] | None,
) -> str:
    """`GeneratedEmail.expert_title` from `academic_title` or legacy `title`."""
    if not expert_row:
        return ""
    t = (expert_row.get("academic_title") or expert_row.get("title") or "").strip()
    if not isinstance(t, str):
        return ""
    return t[:255]
