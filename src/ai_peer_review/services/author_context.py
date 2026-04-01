from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import Author


def build_author_context_snippet(
    unified_document: ResearchhubUnifiedDocument,
    max_chars: int = 4000,
) -> str:
    """
    Short ORCID + profile snippet for feasibility / track-record context in prompts.
    """
    owner = unified_document.created_by
    if not owner:
        return ""
    author = Author.objects.filter(user_id=owner.id).first()
    lines = []
    if author:
        if author.orcid_id:
            lines.append(f"ORCID: {author.orcid_id}")
        if author.headline:
            lines.append(f"Headline: {author.headline}")
        if author.description:
            lines.append(f"Profile: {author.description}")
        if author.university_id:
            uni = author.university
            if uni:
                lines.append(f"Affiliation: {uni.name}")
    else:
        name = f"{owner.first_name} {owner.last_name}".strip()
        if name:
            lines.append(f"ResearchHub author: {name}")
    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        return text[:max_chars] + "\n[TRUNCATED]"
    return text
