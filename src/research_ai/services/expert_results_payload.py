from typing import Any

from research_ai.models import Expert, ExpertSearch
from research_ai.services.expert_display import (
    expert_dict_to_api_payload,
    expert_model_display_name,
)


def expert_model_to_flat_dict(expert: Expert) -> dict[str, Any]:
    return {
        "honorific": expert.honorific,
        "first_name": expert.first_name,
        "middle_name": expert.middle_name,
        "last_name": expert.last_name,
        "name_suffix": expert.name_suffix,
        "academic_title": expert.academic_title,
        "title": expert.academic_title,
        "affiliation": expert.affiliation,
        "expertise": expert.expertise,
        "email": expert.email,
        "notes": expert.notes,
        "sources": expert.sources if isinstance(expert.sources, list) else [],
        "name": expert_model_display_name(expert),
        "last_email_sent_at": expert.last_email_sent_at,
    }


def get_expert_results_payload(expert_search: ExpertSearch) -> list[dict[str, Any]]:
    """Ordered expert dicts for API/email from SearchExpert + Expert rows."""
    rows = list(
        expert_search.search_experts.select_related("expert").order_by("position", "id")
    )
    out = []
    for se in rows:
        d = expert_model_to_flat_dict(se.expert)
        out.append(expert_dict_to_api_payload(d, expert_id=se.expert_id))
    return out
