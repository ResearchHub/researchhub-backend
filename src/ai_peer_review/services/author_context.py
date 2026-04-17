from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import Author


def build_author_context_snippet(
    unified_document: ResearchhubUnifiedDocument,
    max_chars: int = 4000,
) -> str:
    """
    Profile-backed author context for proposal-review prompts.
    """
    owner = unified_document.created_by
    if not owner:
        return ""
    author = Author.objects.filter(user_id=owner.id).first()
    if author:
        text = build_author_context_text(author)
    else:
        name = f"{owner.first_name} {owner.last_name}".strip()
        text = f"ResearchHub author: {name}" if name else ""
    text = (text or "").strip()
    if len(text) > max_chars:
        return text[:max_chars] + "\n[TRUNCATED]"
    return text


def build_author_context_text(author: Author | None) -> str:
    """
    Serialize a ResearchHub Author into factual lines for the peer-review prompt.
    """
    if author is None:
        return ""

    lines: list[str] = []
    fn = (author.first_name or "").strip()
    ln = (author.last_name or "").strip()
    name = f"{fn} {ln}".strip()
    if name:
        lines.append(f"Name: {name}")

    if getattr(author, "headline", None) and str(author.headline).strip():
        headline = str(author.headline).strip()[:2000]
        lines.append(f"Headline: {headline}")

    uni = getattr(author, "university", None)
    if uni is not None and getattr(uni, "name", None):
        affil = str(uni.name).strip()
        city = getattr(uni, "city", None) or ""
        cc = getattr(author, "country_code", None) or ""
        extra = ", ".join(p for p in (city, cc) if p)
        lines.append(
            f"Affiliation (ResearchHub): {affil}" + (f" ({extra})" if extra else "")
        )

    if getattr(author, "description", None) and str(author.description).strip():
        desc = str(author.description).strip()[:4000]
        lines.append(f"Profile summary: {desc}")

    if getattr(author, "orcid_id", None) and str(author.orcid_id).strip():
        lines.append(f"ORCID (on profile): {str(author.orcid_id).strip()}")

    oa_ids = getattr(author, "openalex_ids", None) or []
    if oa_ids:
        preview = ", ".join(str(x) for x in oa_ids[:5] if x)
        if preview:
            lines.append(f"OpenAlex author IDs (on profile): {preview}")

    h = getattr(author, "h_index", None)
    i10 = getattr(author, "i10_index", None)
    if h is not None or i10 is not None:
        lines.append(f"h-index / i10-index (on profile): {h} / {i10}")

    edu = getattr(author, "education", None) or []
    if edu:
        lines.append(f"Education entries (count): {len(edu)}")

    for label, field in (
        ("Google Scholar", "google_scholar"),
        ("LinkedIn", "linkedin"),
    ):
        val = getattr(author, field, None)
        if val:
            lines.append(f"{label}: {str(val).strip()}")

    return "\n".join(lines).strip()
