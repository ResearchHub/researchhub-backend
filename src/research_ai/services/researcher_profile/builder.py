"""Assemble and persist the profile: resolution and selected works.

The entry points live here: ``build_expert_profile`` (no write) and
``build_and_store_expert_profile`` (persists on ``Expert.profile``).
"""

import logging

from django.utils import timezone

from research_ai.services.researcher_profile.resolver import (
    AuthorResolution,
    resolve_openalex_author,
)
from research_ai.services.researcher_profile.works import collect_works
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


def build_expert_profile(
    expert,
    *,
    oa_client: OpenAlex | None = None,
) -> dict:
    """
    Build the source-attributed researcher profile for an ``Expert`` (no write).

    Resolver -> OpenAlex author record -> OpenAlex works. Every stage is
    best-effort: failures are captured in ``errors`` and the profile is
    still returned with whatever was found.
    """
    errors: list[str] = []
    oa = oa_client or OpenAlex()
    try:
        resolution = resolve_openalex_author(expert, client=oa)
    except Exception as exc:  # noqa: BLE001 - resolver is best-effort
        logger.exception("resolve_openalex_author failed")
        resolution = AuthorResolution(match_method="unresolved")
        errors.append(f"resolve: {exc}")
    if resolution.error:
        errors.append(f"resolve: {resolution.error}")

    works, works_errors = collect_works(resolution, oa_client=oa)
    errors.extend(works_errors)

    return {
        "schema_version": _SCHEMA_VERSION,
        "built_at": timezone.now().isoformat(),
        "resolution": resolution.as_dict(),
        "works": [w.as_dict() for w in works],
        "errors": errors,
    }


def build_and_store_expert_profile(expert, **kwargs) -> dict:
    """Build the profile and persist it on ``Expert.profile`` (built once, reused)."""
    profile = build_expert_profile(expert, **kwargs)
    expert.profile = profile
    expert.save(update_fields=["profile", "updated_date"])
    return profile
