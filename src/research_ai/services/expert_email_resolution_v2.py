from research_ai.models import ExpertSearch, SearchExpert
from research_ai.services.expert_display import ExpertDisplay


def resolve_expert_from_search_v2(
    expert_search: ExpertSearch | None, expert_email: str
) -> dict | None:
    """
    Return a dict for ``generate_expert_email`` / ``_normalize_expert_from_resolved``:
    keys name, title, affiliation, expertise, email, notes; or None if no match.
    """
    if expert_search is None:
        return None
    email = ExpertDisplay.normalize_email(expert_email)
    if not email:
        return None
    se = (
        SearchExpert.objects.filter(expert_search_id=expert_search.id)
        .select_related("expert")
        .filter(expert__email__iexact=email)
        .first()
    )
    if se is None:
        return None
    ex = se.expert
    return {
        "name": ExpertDisplay.personal_name_for(ex),
        "title": (ex.academic_title or "").strip(),
        "affiliation": (ex.affiliation or "").strip(),
        "expertise": (ex.expertise or "").strip(),
        "email": (ex.email or "").strip(),
        "notes": (ex.notes or "").strip(),
    }
