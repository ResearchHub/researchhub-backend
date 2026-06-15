"""Assemble and persist the profile via the resolution escalation ladder.

The entry points live here: ``build_expert_profile`` (no write) and
``build_and_store_expert_profile`` (persists on ``Expert.profile``).

The ladder escalates only as far as needed, stopping at the first rung that is
confident, so the LLM runs at most once per expert:

1. **source-link** -- a cited OpenAlex/ORCID id (certain).
2. **name / name+affiliation** -- a lone, strong name match is accepted directly.
3. **name-llm** -- ambiguous or borderline candidates are handed to the LLM
   disambiguator, which picks one or abstains.

When the disambiguator abstains (or there are no candidates at all) the expert
is left ``unresolved`` rather than guessed at. Every stage is best-effort:
failures are captured in ``errors`` and the profile is still returned with
whatever was found.
"""

import logging

from django.utils import timezone

from research_ai.services.researcher_profile.disambiguator import disambiguate_author
from research_ai.services.researcher_profile.resolver import (
    AuthorResolution,
    NameCandidates,
    confident_single,
    gather_name_candidates,
    resolve_via_source_link,
)
from research_ai.services.researcher_profile.works import collect_works
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


def _resolution_from_candidate(
    top: tuple[float, dict], candidates: NameCandidates
) -> AuthorResolution:
    """Build a resolution for a directly-accepted (confident) name candidate."""
    name_score, record = top
    if candidates.scoped:
        method, score = "name+affiliation", 0.6 * name_score + 0.4
    else:
        method, score = "name", name_score
    return AuthorResolution(
        openalex_author_id=record.get("id"),
        display_name=record.get("display_name"),
        match_score=score,
        match_method=method,
        candidates_considered=candidates.candidates_considered,
        record=record,
    )


def _resolve_and_collect(expert, oa: OpenAlex, *, llm, errors: list[str]):
    """Walk the escalation ladder; return ``(resolution, works, disambiguation)``.

    ``disambiguation`` is the ``DisambiguationResult`` when the LLM was consulted
    (chosen or abstained), else ``None`` -- the builder surfaces it for audit.
    """
    # Rung 1: a cited OpenAlex/ORCID id is certain -- no LLM needed.
    try:
        source = resolve_via_source_link(expert, client=oa)
    except Exception as exc:  # noqa: BLE001 - resolver is best-effort
        logger.exception("source-link resolution failed")
        errors.append(f"resolve: {exc}")
        source = None
    if source:
        works, works_errors = collect_works(source, oa_client=oa)
        errors.extend(works_errors)
        return source, works, None

    # Rungs 2/3: gather name candidates.
    try:
        candidates = gather_name_candidates(expert, client=oa)
    except Exception as exc:  # noqa: BLE001 - resolver is best-effort
        logger.exception("name candidate gathering failed")
        errors.append(f"resolve: {exc}")
        candidates = NameCandidates()
    if candidates.error:
        errors.append(f"resolve: {candidates.error}")

    # Rung 2: a lone, strong match is accepted directly.
    top = confident_single(candidates.scored)
    if top is not None:
        resolution = _resolution_from_candidate(top, candidates)
        works, works_errors = collect_works(resolution, oa_client=oa)
        errors.extend(works_errors)
        return resolution, works, None

    # Rung 3: ambiguous or borderline -- let the LLM adjudicate.
    disambiguation = None
    if candidates.scored:
        disambiguation = disambiguate_author(expert, candidates.scored, llm=llm)
        if disambiguation.error:
            errors.append(f"disambiguate: {disambiguation.error}")
        if disambiguation.chosen:
            resolution = AuthorResolution(
                openalex_author_id=disambiguation.record.get("id"),
                display_name=disambiguation.record.get("display_name"),
                match_score=disambiguation.confidence,
                match_method="name-llm",
                candidates_considered=candidates.candidates_considered,
                record=disambiguation.record,
            )
            works, works_errors = collect_works(resolution, oa_client=oa)
            errors.extend(works_errors)
            return resolution, works, disambiguation

    # No confident match, and the disambiguator did not (or could not) pick one.
    resolution = AuthorResolution(
        match_method="unresolved",
        candidates_considered=candidates.candidates_considered,
    )
    return resolution, [], disambiguation


def build_expert_profile(
    expert,
    *,
    oa_client: OpenAlex | None = None,
    llm=None,
) -> dict:
    """
    Build the source-attributed researcher profile for an ``Expert`` (no write).

    ``llm`` (a ``BedrockLLMService``) is injectable for testing; when omitted it
    is constructed lazily only if the disambiguation rung is reached, so an
    easily-resolved expert never instantiates it.
    """
    errors: list[str] = []
    oa = oa_client or OpenAlex()

    resolution, works, disambiguation = _resolve_and_collect(
        expert, oa, llm=llm, errors=errors
    )

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
