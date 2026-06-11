"""Assemble and persist the profile: selected works and context text.

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
_CONTEXT_MAX_CHARS = 8000


def _build_context_text(
    expert,
    resolution: AuthorResolution,
    works_text: str,
    *,
    max_chars: int = _CONTEXT_MAX_CHARS,
) -> str:
    chunks: list[str] = []

    head = [f"Researcher profile: {expert.full_name}".rstrip(": ")]
    if resolution.openalex_author_id:
        head.append(f"OpenAlex author: {resolution.openalex_author_id}")
    chunks.append("\n".join(head))

    if works_text.strip():
        chunks.append(
            "--- Selected works (first/last-author papers prioritized) ---\n"
            + works_text.strip()
        )

    text = "\n\n".join(c for c in chunks if c.strip()).strip()
    if len(text) > max_chars:
        return text[:max_chars] + "\n[TRUNCATED]"
    return text


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
    works_text = "\n".join(f"- {w.label}" for w in works)

    context_text = _build_context_text(expert, resolution, works_text)

    return {
        "schema_version": _SCHEMA_VERSION,
        "built_at": timezone.now().isoformat(),
        "resolution": resolution.as_dict(),
        "works": [w.as_dict() for w in works],
        "context_text": context_text,
        "errors": errors,
    }


def build_and_store_expert_profile(expert, **kwargs) -> dict:
    """Build the profile and persist it on ``Expert.profile`` (built once, reused)."""
    profile = build_expert_profile(expert, **kwargs)
    expert.profile = profile
    expert.save(update_fields=["profile", "updated_date"])
    return profile
