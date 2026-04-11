from typing import Any

from research_ai.models import ExpertSearch
from research_ai.services.expert_display import expert_to_api_row


def get_expert_results_payload(expert_search: ExpertSearch) -> list[dict[str, Any]]:
    """Ordered expert dicts for API/email from SearchExpert + Expert rows."""
    rows = list(
        expert_search.search_experts.select_related("expert").order_by("position", "id")
    )
    return [expert_to_api_row(se.expert, expert_id=se.expert_id) for se in rows]
