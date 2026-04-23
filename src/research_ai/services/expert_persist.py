"""
Persistence helpers for Expert and SearchExpert (upsert, replace, email timestamps).
"""

from datetime import datetime
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.db import transaction
from django.utils import timezone

from research_ai.models import Expert, ExpertSearch, SearchExpert
from research_ai.services.expert_display import normalize_expert_email


def upsert_expert_from_parsed_dict(data: dict[str, Any]) -> Expert:
    """
    Create or update an Expert by normalized email. Does not change `registered_user`
    or `last_email_sent_at` (those are managed elsewhere).
    """
    email = normalize_expert_email(data.get("email", ""))
    if not email:
        raise ValueError("expert email is required")
    try:
        EmailValidator()(email)
    except ValidationError as e:
        raise ValueError("invalid expert email") from e

    def _s(key: str) -> str:
        v = data.get(key, "")
        return (v if isinstance(v, str) else str(v or "")).strip()

    sources = data.get("sources")
    if sources is None:
        sources = []
    if not isinstance(sources, list):
        sources = list(sources) if sources else []

    defaults = {
        "honorific": _s("honorific"),
        "first_name": _s("first_name"),
        "middle_name": _s("middle_name"),
        "last_name": _s("last_name"),
        "name_suffix": _s("name_suffix"),
        "academic_title": _s("academic_title"),
        "affiliation": _s("affiliation"),
        "expertise": _s("expertise"),
        "notes": _s("notes"),
        "sources": sources,
    }
    expert, _ = Expert.objects.update_or_create(email=email, defaults=defaults)
    return expert


@transaction.atomic
def replace_search_experts_for_search(
    search_id: int, experts: list[dict[str, Any]]
) -> int:
    """
    Replace all SearchExpert rows for this search with the given experts in order.
    Upserts Expert rows. Returns the number of membership rows created.
    """
    ExpertSearch.objects.get(pk=search_id)

    SearchExpert.objects.filter(expert_search_id=search_id).delete()
    n = 0
    for pos, row in enumerate(experts):
        ex = upsert_expert_from_parsed_dict(row)
        SearchExpert.objects.create(
            expert_search_id=search_id,
            expert=ex,
            position=pos,
        )
        n += 1
    return n


def mark_expert_last_email_sent_at(
    email: str,
    *,
    at: datetime | None = None,
) -> int:
    """
    Set `last_email_sent_at` for the Expert with this email. Returns the number
    of rows updated (0 or 1).
    """
    em = normalize_expert_email(email)
    if not em:
        return 0
    ts = at if at is not None else timezone.now()
    return Expert.objects.filter(email=em).update(last_email_sent_at=ts)
