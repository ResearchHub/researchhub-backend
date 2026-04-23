from typing import Any

from django.db import transaction
from django.utils import timezone

from research_ai.models import Expert, SearchExpert
from research_ai.services.expert_display import normalize_expert_email
from research_ai.utils import trimmed_str


def upsert_expert_from_parsed_dict(d: dict[str, Any]) -> Expert:
    """
    One row per email. Non-empty fields from the latest parse overwrite existing values.
    """
    email = normalize_expert_email(d.get("email") or "")
    if not email:
        raise ValueError("Expert email is required")

    sources = d.get("sources")
    if not isinstance(sources, list):
        sources = []

    candidate = {
        "honorific": trimmed_str(d.get("honorific"), max_len=64),
        "first_name": trimmed_str(d.get("first_name"), max_len=255),
        "middle_name": trimmed_str(d.get("middle_name"), max_len=255),
        "last_name": trimmed_str(d.get("last_name"), max_len=255),
        "name_suffix": trimmed_str(d.get("name_suffix"), max_len=64),
        "academic_title": trimmed_str(d.get("academic_title"), max_len=255),
        "affiliation": trimmed_str(d.get("affiliation")),
        "expertise": trimmed_str(d.get("expertise")),
        "notes": trimmed_str(d.get("notes")),
    }

    expert = Expert.objects.filter(email__iexact=email).first()
    if expert is None:
        return Expert.objects.create(
            email=email,
            honorific=candidate["honorific"],
            first_name=candidate["first_name"],
            middle_name=candidate["middle_name"],
            last_name=candidate["last_name"],
            name_suffix=candidate["name_suffix"],
            academic_title=candidate["academic_title"],
            affiliation=candidate["affiliation"] or "",
            expertise=candidate["expertise"] or "",
            notes=candidate["notes"] or "",
            sources=sources,
        )

    for field, val in candidate.items():
        if val:
            setattr(expert, field, val)
    if sources:
        expert.sources = sources
    expert.save()
    return expert


@transaction.atomic
def replace_search_experts_for_search(
    expert_search_id: int, expert_dicts: list[dict[str, Any]]
) -> int:
    """Replace SearchExpert links; upsert Experts. Returns count."""
    SearchExpert.objects.filter(expert_search_id=expert_search_id).delete()
    for position, d in enumerate(expert_dicts):
        expert = upsert_expert_from_parsed_dict(d)
        SearchExpert.objects.create(
            expert_search_id=expert_search_id,
            expert_id=expert.id,
            position=position,
        )
    return len(expert_dicts)


def mark_expert_last_email_sent_at(email: str) -> None:
    """Set last_email_sent_at=now on the Expert row for this address, if one exists."""
    em = normalize_expert_email(email)
    if not em:
        return
    Expert.objects.filter(email__iexact=em).update(last_email_sent_at=timezone.now())
