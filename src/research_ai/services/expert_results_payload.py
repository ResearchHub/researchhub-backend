"""
Build expert result lists for API from ExpertSearch (relational or legacy JSON).
"""

from typing import Any

from research_ai.models import Expert, ExpertSearch, SearchExpert
from research_ai.services.expert_display import (
    expert_dict_to_api_payload,
    expert_model_display_name,
)


def expert_model_to_flat_dict(expert: Expert) -> dict[str, Any]:
    """
    Expert ORM row to the flat dict shape used in expert_results-style payloads.
    Includes legacy `title` as an alias for `academic_title` and computed `name`.
    """
    display = expert_model_display_name(expert)
    at = (expert.academic_title or "").strip()
    return {
        "id": expert.id,
        "email": expert.email,
        "honorific": expert.honorific,
        "first_name": expert.first_name,
        "middle_name": expert.middle_name,
        "last_name": expert.last_name,
        "name_suffix": expert.name_suffix,
        "academic_title": at,
        "name": display,
        "title": at,
        "affiliation": expert.affiliation,
        "expertise": expert.expertise,
        "notes": expert.notes,
        "sources": expert.sources or [],
    }


def get_expert_results_payload(expert_search: ExpertSearch) -> list[dict[str, Any]]:
    """
    Return ordered expert rows for the search: SearchExpert + Expert when present,
    otherwise fall back to legacy `expert_search.expert_results` JSON.
    """
    rows: list[dict[str, Any]] = []
    se_list = list(
        SearchExpert.objects.filter(expert_search=expert_search)
        .select_related("expert")
        .order_by("position", "id")
    )
    if se_list:
        for se in se_list:
            flat = expert_model_to_flat_dict(se.expert)
            rows.append(expert_dict_to_api_payload(flat))
        return rows
    for item in expert_search.expert_results or []:
        if not isinstance(item, dict):
            continue
        rows.append(expert_dict_to_api_payload(item))
    return rows
