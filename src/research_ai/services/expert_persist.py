from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.functions import Lower
from django.utils import timezone

from research_ai.models import Expert, SearchExpert
from research_ai.services.expert_display import ExpertDisplay
from research_ai.utils import trimmed_str

User = get_user_model()


class ExpertPersist:
    """Create/update ``Expert`` rows and ``SearchExpert`` links from parsed finder dicts."""

    @staticmethod
    def upsert_from_parsed_dict(d: dict[str, Any]) -> Expert:
        """
        One row per email. Non-empty fields from the latest parse overwrite existing values.
        """
        email = ExpertDisplay.normalize_email(d.get("email") or "")
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
                registered_user_id=ExpertPersist._find_registered_user_id(email),
            )

        for field, val in candidate.items():
            if val:
                setattr(expert, field, val)
        if sources:
            expert.sources = sources
        if expert.registered_user_id is None:
            match_id = ExpertPersist._find_registered_user_id(email)
            if match_id is not None:
                expert.registered_user_id = match_id
        expert.save()
        return expert

    @staticmethod
    def _find_registered_user_id(email: str) -> int | None:
        """Return the ``User.id`` whose email matches case-insensitively, else None.

        Uses the ``LOWER(email)`` functional index on the user table so this stays a
        single indexed lookup even as the user table grows.
        """
        if not email:
            return None
        return (
            User.objects.alias(_email_lower=Lower("email"))
            .filter(_email_lower=email)
            .values_list("id", flat=True)
            .first()
        )

    @classmethod
    def replace_search_experts_for_search(
        cls,
        expert_search_id: int,
        expert_dicts: list[dict[str, Any]],
    ) -> int:
        """Replace SearchExpert links; upsert Experts. Returns count."""
        with transaction.atomic():
            SearchExpert.objects.filter(expert_search_id=expert_search_id).delete()
            for position, d in enumerate(expert_dicts):
                expert = cls.upsert_from_parsed_dict(d)
                SearchExpert.objects.create(
                    expert_search_id=expert_search_id,
                    expert_id=expert.id,
                    position=position,
                )
            return len(expert_dicts)

    @staticmethod
    def mark_last_email_sent_at(email: str) -> None:
        """Set last_email_sent_at=now on the Expert row for this address, if one exists."""
        em = ExpertDisplay.normalize_email(email)
        if not em:
            return
        Expert.objects.filter(email__iexact=em).update(
            last_email_sent_at=timezone.now()
        )

    @staticmethod
    def tag_manual_source(expert: Expert, user) -> None:
        """Mark this expert as manually added and append an audit entry to
        ``expert.sources``.

        Sets ``is_manually_added=True`` (the load-bearing flag used to surface
        manual entries first in search results) and appends a
        ``{"type": "manual", ...}`` marker to ``sources`` for audit history.

        Idempotent per user for the audit entry: skips appending if a manual
        entry by the same user is already present. Existing (e.g. LLM-populated)
        source entries are preserved.
        """
        sources = expert.sources if isinstance(expert.sources, list) else []
        user_id = getattr(user, "id", None)
        update_fields = []
        if not expert.is_manually_added:
            expert.is_manually_added = True
            update_fields.append("is_manually_added")
        already_tagged = any(
            isinstance(entry, dict)
            and entry.get("type") == "manual"
            and entry.get("added_by") == user_id
            for entry in sources
        )
        if not already_tagged:
            sources.append(
                {
                    "type": "manual",
                    "added_by": user_id,
                    "added_at": timezone.now().isoformat(),
                }
            )
            expert.sources = sources
            update_fields.append("sources")
        if update_fields:
            expert.save(update_fields=update_fields)
