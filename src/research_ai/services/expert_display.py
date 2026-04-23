from research_ai.models import Expert


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
    last = (last_name or "").strip()
    suf = (name_suffix or "").strip()
    fb = (fallback_name or "").strip()

    if not (f or m or last) and fb:
        return fb

    parts: list[str] = []
    if h:
        hn = h if h.endswith(".") else f"{h}."
        parts.append(hn)
    nm = " ".join(x for x in (f, m, last) if x)
    if nm:
        parts.append(nm)
    core = " ".join(parts).strip()
    if not core:
        return fb
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


def normalize_expert_email(email: str) -> str:
    return (email or "").strip().lower()
