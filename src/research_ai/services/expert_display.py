from typing import Any


def build_expert_display_name(
    *,
    honorific: str = "",
    first_name: str = "",
    middle_name: str = "",
    last_name: str = "",
    name_suffix: str = "",
    fallback_name: str = "",
) -> str:
    """
    Human-readable name for PDF/CSV/API. Prefer structured parts; else fallback.
    """
    h = (honorific or "").strip()
    f = (first_name or "").strip()
    m = (middle_name or "").strip()
    l = (last_name or "").strip()
    suf = (name_suffix or "").strip()
    fb = (fallback_name or "").strip()

    if not (f or m or l) and fb:
        return fb

    parts: list[str] = []
    if h:
        hn = h if h.endswith(".") else f"{h}."
        parts.append(hn)
    nm = " ".join(x for x in (f, m, l) if x)
    if nm:
        parts.append(nm)
    core = " ".join(parts).strip()
    if not core:
        return fb
    if suf:
        return f"{core}, {suf}" if not suf.startswith(",") else f"{core}{suf}"
    return core


def expert_model_display_name(expert) -> str:
    """Build display name from an Expert model instance."""
    return build_expert_display_name(
        honorific=expert.honorific,
        first_name=expert.first_name,
        middle_name=expert.middle_name,
        last_name=expert.last_name,
        name_suffix=expert.name_suffix,
    )


def expert_dict_to_api_payload(
    d: dict[str, Any],
    *,
    expert_id: int | None = None,
) -> dict[str, Any]:
    """
    Normalize a parsed expert dict (LLM or DB-backed) to API shape.
    """
    name = build_expert_display_name(
        honorific=d.get("honorific") or "",
        first_name=d.get("first_name") or "",
        middle_name=d.get("middle_name") or "",
        last_name=d.get("last_name") or "",
        name_suffix=d.get("name_suffix") or "",
        fallback_name=d.get("name") or "",
    )
    out = {
        "expert_id": expert_id,
        "honorific": d.get("honorific") or "",
        "first_name": d.get("first_name") or "",
        "middle_name": d.get("middle_name") or "",
        "last_name": d.get("last_name") or "",
        "name_suffix": d.get("name_suffix") or "",
        "academic_title": d.get("academic_title") or d.get("title") or "",
        "affiliation": d.get("affiliation") or "",
        "expertise": d.get("expertise") or "",
        "email": d.get("email") or "",
        "notes": d.get("notes") or "",
        "sources": d.get("sources") if isinstance(d.get("sources"), list) else [],
        "name": name,
    }
    return out


def normalize_expert_email(email: str) -> str:
    return (email or "").strip().lower()
