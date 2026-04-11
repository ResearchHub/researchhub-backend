from typing import Any

from research_ai.models import Expert


def build_expert_display_name(
    *,
    honorific: str = "",
    first_name: str = "",
    middle_name: str = "",
    last_name: str = "",
    name_suffix: str = "",
) -> str:
    """
    Human-readable name for PDF/CSV/API from structured fields only.
    """
    h = (honorific or "").strip()
    f = (first_name or "").strip()
    m = (middle_name or "").strip()
    ln = (last_name or "").strip()
    suf = (name_suffix or "").strip()

    parts: list[str] = []
    if h:
        hn = h if h.endswith(".") else f"{h}."
        parts.append(hn)
    nm = " ".join(x for x in (f, m, ln) if x)
    if nm:
        parts.append(nm)
    core = " ".join(parts).strip()
    if not core:
        return ""
    if suf:
        return f"{core}, {suf}" if not suf.startswith(",") else f"{core}{suf}"
    return core


def expert_model_display_name(expert: Expert) -> str:
    """Build display name from an Expert model instance."""
    return build_expert_display_name(
        honorific=expert.honorific,
        first_name=expert.first_name,
        middle_name=expert.middle_name,
        last_name=expert.last_name,
        name_suffix=expert.name_suffix,
    )


def expert_to_api_row(
    expert: Expert, *, expert_id: int | None = None
) -> dict[str, Any]:
    """API-shaped expert dict from a persisted Expert (SearchExpert.expert_id for expert_id)."""
    at = (
        (expert.academic_title or "").strip()
        if isinstance(expert.academic_title, str)
        else ""
    )
    name = expert_model_display_name(expert)
    return {
        "expert_id": expert_id if expert_id is not None else expert.id,
        "honorific": expert.honorific or "",
        "first_name": expert.first_name or "",
        "middle_name": expert.middle_name or "",
        "last_name": expert.last_name or "",
        "name_suffix": expert.name_suffix or "",
        "academic_title": at,
        "title": at,
        "affiliation": expert.affiliation or "",
        "expertise": expert.expertise or "",
        "email": expert.email or "",
        "notes": expert.notes or "",
        "sources": expert.sources if isinstance(expert.sources, list) else [],
        "name": name,
        "last_email_sent_at": expert.last_email_sent_at,
    }


def expert_dict_to_api_payload(
    d: dict[str, Any],
    *,
    expert_id: int | None = None,
) -> dict[str, Any]:
    """
    Normalize a parsed expert dict (e.g. LLM table row) to API shape.
    Display name is derived only from structured name fields.
    """
    name = build_expert_display_name(
        honorific=d.get("honorific") or "",
        first_name=d.get("first_name") or "",
        middle_name=d.get("middle_name") or "",
        last_name=d.get("last_name") or "",
        name_suffix=d.get("name_suffix") or "",
    )
    raw_at = d.get("academic_title")
    if not isinstance(raw_at, str):
        raw_at = ""
    at = raw_at.strip()
    if not at:
        legacy_t = d.get("title")
        if isinstance(legacy_t, str):
            at = legacy_t.strip()
    out = {
        "expert_id": expert_id,
        "honorific": d.get("honorific") or "",
        "first_name": d.get("first_name") or "",
        "middle_name": d.get("middle_name") or "",
        "last_name": d.get("last_name") or "",
        "name_suffix": d.get("name_suffix") or "",
        "academic_title": at,
        "title": at,
        "affiliation": d.get("affiliation") or "",
        "expertise": d.get("expertise") or "",
        "email": d.get("email") or "",
        "notes": d.get("notes") or "",
        "sources": d.get("sources") if isinstance(d.get("sources"), list) else [],
        "name": name,
        "last_email_sent_at": d.get("last_email_sent_at"),
    }
    return out


def normalize_expert_email(email: str) -> str:
    return (email or "").strip().lower()


def expert_name_for_generated_email_storage(
    resolved: dict, *, max_length: int = 255
) -> str:
    """
    Denormalized expert_name for GeneratedEmail rows.

    Matches {{expert.name}} in fixed templates: honorific + first + middle + last
    """
    s = build_expert_display_name(
        honorific=resolved.get("honorific") or "",
        first_name=resolved.get("first_name") or "",
        middle_name=resolved.get("middle_name") or "",
        last_name=resolved.get("last_name") or "",
        name_suffix="",
    )
    return s[:max_length]


def expert_title_for_generated_email_storage(
    resolved: dict, *, max_length: int = 255
) -> str:
    """Academic / job title from API-shaped resolved expert."""
    raw = resolved.get("academic_title") or ""
    t = raw.strip() if isinstance(raw, str) else ""
    return t[:max_length]
