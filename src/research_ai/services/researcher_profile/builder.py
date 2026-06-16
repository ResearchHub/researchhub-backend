"""Assemble and persist the researcher profile.

The entry points live here: ``build_expert_profile`` (no write) and
``build_and_store_expert_profile`` (persists on ``Expert.profile``).

Resolution -- mapping the ``Expert`` to an OpenAlex author, including the LLM
disambiguation rung -- is delegated to ``resolver.resolve_author``. The builder
then collects the resolved author's works and assembles the profile dict. Every
stage is best-effort: failures are captured in ``errors`` and the profile is
still returned with whatever was found.
"""

import logging

from django.utils import timezone

from research_ai.services.researcher_profile.resolver import resolve_author
from research_ai.services.researcher_profile.works import collect_works
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


def build_expert_profile(
    expert,
    *,
    oa_client: OpenAlex | None = None,
    llm=None,
) -> dict:
    """
    Build the source-attributed researcher profile for an ``Expert`` (no write).

    Resolution (including LLM disambiguation) is delegated to ``resolve_author``;
    the builder collects the resolved author's works and assembles the profile
    dict. ``llm`` (a ``BedrockLLMService``) is injectable for testing; when
    omitted it is constructed lazily only if the disambiguation rung is reached,
    so an easily-resolved expert never instantiates it.
    """
    oa = oa_client or OpenAlex()

    resolution, disambiguation, errors = resolve_author(expert, client=oa, llm=llm)

    # ``collect_works`` no-ops for an unresolved author, so this is safe to call
    # unconditionally.
    works, works_errors = collect_works(resolution, oa_client=oa)
    errors.extend(works_errors)

    resolution_dict = resolution.as_dict()
    if disambiguation is not None:
        resolution_dict["disambiguation"] = {
            "confidence": round(disambiguation.confidence, 3),
            "reasoning": disambiguation.reasoning,
            "chosen": disambiguation.chosen,
        }

    return {
        "schema_version": _SCHEMA_VERSION,
        "built_at": timezone.now().isoformat(),
        "resolution": resolution_dict,
        "works": [w.as_dict() for w in works],
        "errors": errors,
    }


def build_and_store_expert_profile(expert, **kwargs) -> dict:
    """Build the profile and persist it on ``Expert.profile`` (built once, reused)."""
    profile = build_expert_profile(expert, **kwargs)
    expert.profile = profile
    expert.save(update_fields=["profile", "updated_date"])
    return profile
