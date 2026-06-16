"""Resolver: map an ``Expert`` to an OpenAlex author id.

``resolve_author`` is the single entry point. It walks a ladder from most to
least certain, stopping at the first rung that produces a match and returning
"unresolved" rather than guessing:

1. **source-link** -- an ORCID iD the expert finder cited in ``expert.sources``,
   used only as a lookup key. A cited OpenAlex author id is *not* trusted (the
   finder fabricates them), so it falls through to the name rungs.
2. **name+affiliation** -- the affiliation resolves to an OpenAlex institution,
   the author search is scoped to it, and a lone strong match is accepted only
   when name *and* institution corroborate; a name-only match escalates.
3. **name-llm** -- the remaining candidates go to the web-search disambiguator,
   which picks one, reports an identifier it found online, or abstains.
4. **web-id** -- an ORCID/OpenAlex id the disambiguator found for a person not
   among the candidates, re-fetched and name-validated before it is trusted.

The expert's ``affiliation``/``expertise`` are machine-generated, not
self-reported -- both sides of the match are noisy, so the ladder misses rather
than accepts a weak match.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass, field

from research_ai.services.openai_llm_service import OpenAIWebSearchLLMService
from research_ai.services.researcher_external_context import (
    fetch_openalex_author_record,
)
from research_ai.services.researcher_profile.disambiguator import (
    DisambiguationResult,
    disambiguate_author,
)
from utils.openalex import OpenAlex, normalize_orcid

logger = logging.getLogger(__name__)

# Minimum name-match strength to count as a candidate. Conservative: a wrong
# match would attribute someone else's track record to the expert.
NAME_SCORE_STRONG = 0.6

# A single candidate at or above this is taken directly, no LLM: 0.85+ means the
# full first name is present (exact full-name match scores 1.0). A lone
# initial-only match (0.6) clears STRONG but not this, so it escalates.
NAME_SCORE_CONFIDENT = 0.85

# Score for a resolution recovered from a web-discovered identifier: high (it was
# re-fetched and name-validated) but below a directly-cited source link.
WEB_ID_SCORE = 0.9

# Candidate choices below this model-reported confidence are treated as abstains.
LLM_CHOICE_MIN_CONFIDENCE = 0.75


def _norm(value: str) -> str:
    """Lowercase, strip accents, collapse to ``[a-z0-9 ]`` tokens."""
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9\s]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class AuthorResolution:
    openalex_author_id: str | None = None
    display_name: str | None = None
    match_score: float = 0.0
    match_method: str = "unresolved"
    candidates_considered: int = 0
    record: dict | None = None  # raw OpenAlex author entity; not serialized
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "openalex_author_id": self.openalex_author_id,
            "display_name": self.display_name,
            "match_score": round(self.match_score, 3),
            "match_method": self.match_method,
            "candidates_considered": self.candidates_considered,
        }


def _name_score(expert, record: dict) -> float:
    """0..1 confidence the candidate's name matches the expert's."""
    first = _norm(getattr(expert, "first_name", ""))
    # Compound surnames ("van der Berg", "Garcia-Lopez") span several tokens.
    last_tokens = set(_norm(getattr(expert, "last_name", "")).split())
    if not last_tokens:
        return 0.0
    candidates = [record.get("display_name") or ""]
    candidates.extend(record.get("display_name_alternatives") or [])
    best = 0.0
    for cand in candidates:
        toks = _norm(cand).split()
        if not toks or not last_tokens.issubset(toks):
            continue
        if first and first in toks:
            best = max(best, 1.0 if toks[0] == first else 0.85)
        elif first and toks[0][:1] == first[:1]:
            best = max(best, 0.6)
        else:
            best = max(best, 0.3)
    return best


def _name_scored_candidates(expert, records: list[dict]) -> list[tuple[float, dict]]:
    """Candidates with a strong-enough name match, best first."""
    scored = [
        (ns, rec)
        for rec in records
        if (ns := _name_score(expert, rec)) >= NAME_SCORE_STRONG
    ]
    scored.sort(key=lambda t: (t[0], t[1].get("cited_by_count") or 0), reverse=True)
    return scored


def _resolve_institution_id(affiliation: str, *, client: OpenAlex) -> str | None:
    """Resolve the finder-generated affiliation string to an OpenAlex institution.

    Delegates entity resolution (abbreviations, aliases, other languages) to
    OpenAlex's institutions search. Best-effort: returns ``None`` on any miss.
    """
    query = (affiliation or "").strip()
    if not query:
        return None
    try:
        resp = client.search_institutions(query)
        results = (resp or {}).get("results") or []
        for inst in results:
            inst_id = (inst or {}).get("id")
            if inst_id:
                return inst_id
    except Exception as exc:  # noqa: BLE001 - institution scoping is best-effort
        logger.info("OpenAlex institution search failed for %r: %s", query, exc)
    return None


# Escalation-ladder primitives, composed by ``resolve_author`` below.


def resolve_via_source_link(expert, *, client: OpenAlex) -> AuthorResolution | None:
    """Rung 1: an ORCID iD the expert finder already cited (used as a lookup key).

    Returns a certain (score 1.0) resolution, or ``None`` when no ORCID is cited,
    OpenAlex has no author behind it, or the name doesn't match.
    """
    src_orcid, _ = expert.source_ids
    if not src_orcid:
        return None
    record = fetch_openalex_author_record(orcid_bare=src_orcid, client=client)
    if not record:
        return None
    if _name_score(expert, record) < NAME_SCORE_CONFIDENT:
        logger.info(
            "OpenAlex author fetched by cited ORCID did not name-match expert: %s",
            record.get("id"),
        )
        return None
    return AuthorResolution(
        openalex_author_id=record.get("id"),
        display_name=record.get("display_name"),
        match_score=1.0,
        match_method="source-link",
        record=record,
    )


@dataclass
class NameCandidates:
    """Name-strong author candidates for an expert, best first.

    ``scoped`` is ``True`` when the candidates came from the institution-scoped
    search. Only scoped candidates can be accepted directly; unscoped ones always
    escalate to the disambiguator.
    """

    scored: list[tuple[float, dict]] = field(default_factory=list)
    institution_id: str | None = None
    scoped: bool = False
    candidates_considered: int = 0
    error: str | None = None


def gather_name_candidates(expert, *, client: OpenAlex) -> NameCandidates:
    """Gather name-strong author candidates, preferring institution-scoped hits.

    Returns the whole candidate set so the disambiguator can adjudicate.
    Best-effort: search failures surface in ``error`` and yield an empty set.
    """
    name = expert.full_name
    if not name:
        return NameCandidates()

    institution_id = _resolve_institution_id(
        getattr(expert, "affiliation", ""), client=client
    )

    # Institution-scoped name search.
    if institution_id:
        try:
            resp = client.search_authors_via_name(name, institution_id=institution_id)
            results = resp.get("results") or []
        except Exception as exc:  # noqa: BLE001 - fall through to unscoped search
            logger.info("Institution-scoped author search failed: %s", exc)
            results = []
        scored = _name_scored_candidates(expert, results)
        if scored:
            return NameCandidates(
                scored=scored,
                institution_id=institution_id,
                scoped=True,
                candidates_considered=len(results),
            )

    # Unscoped name search.
    try:
        resp = client.search_authors_via_name(name)
    except Exception as exc:  # noqa: BLE001 - network/parse errors are non-fatal
        logger.info("OpenAlex author search failed for %r: %s", name, exc)
        return NameCandidates(institution_id=institution_id, error=str(exc))
    results = resp.get("results") or []
    return NameCandidates(
        scored=_name_scored_candidates(expert, results),
        institution_id=institution_id,
        scoped=False,
        candidates_considered=len(results),
    )


def confident_single(scored: list[tuple[float, dict]]) -> tuple[float, dict] | None:
    """The lone, strong-enough candidate to accept without the LLM, else ``None``.

    Exactly one candidate, at ``NAME_SCORE_CONFIDENT``+. Two-plus candidates or a
    single borderline one are escalated instead.
    """
    if len(scored) == 1 and scored[0][0] >= NAME_SCORE_CONFIDENT:
        return scored[0]
    return None


def _resolution_from_candidate(
    top: tuple[float, dict], candidates: NameCandidates
) -> AuthorResolution:
    """Build a ``name+affiliation`` resolution for a directly-accepted candidate.

    Only used on the scoped (institution-corroborated) confident path; the
    institution match blends into the score.
    """
    name_score, record = top
    return AuthorResolution(
        openalex_author_id=record.get("id"),
        display_name=record.get("display_name"),
        match_score=0.6 * name_score + 0.4,
        match_method="name+affiliation",
        candidates_considered=candidates.candidates_considered,
        record=record,
    )


def _resolve_found_identifier(
    expert, disambiguation: DisambiguationResult, *, client: OpenAlex
) -> AuthorResolution | None:
    """Re-fetch a web-reported identifier, accepting it only if the name matches.

    The model can hallucinate ids, so the fetched record must name-validate
    (``NAME_SCORE_CONFIDENT``+) before it is trusted. ORCID is preferred as the
    lookup key. Returns ``None`` when the id is bogus, the lookup fails, or the
    name doesn't validate.
    """
    orcid = normalize_orcid(disambiguation.found_orcid)
    try:
        record = fetch_openalex_author_record(
            orcid_bare=orcid,
            openalex_author_ref=disambiguation.found_openalex_id,
            client=client,
        )
    except Exception as exc:  # noqa: BLE001 - web-id lookup is best-effort
        logger.info("web-id lookup failed: %s", exc)
        return None
    if not record or _name_score(expert, record) < NAME_SCORE_CONFIDENT:
        return None
    return AuthorResolution(
        openalex_author_id=record.get("id"),
        display_name=record.get("display_name"),
        match_score=WEB_ID_SCORE,
        match_method="web-id",
        record=record,
    )


def resolve_author(
    expert,
    *,
    client: OpenAlex | None = None,
    llm: OpenAIWebSearchLLMService | None = None,
) -> tuple[AuthorResolution, DisambiguationResult | None, list[str]]:
    """Resolve an ``Expert`` to an OpenAlex author, escalating only as needed.

    Walks the full ladder from the module docstring, stopping at the first
    confident rung so the LLM disambiguator runs at most once. ``llm`` is
    injectable for testing; when omitted it is constructed lazily only if the
    disambiguation rung is reached. Best-effort: per-rung failures are collected
    and returned, never raised.

    Returns ``(resolution, disambiguation, errors)`` where ``disambiguation`` is
    set when the disambiguator was consulted, else ``None``.
    """
    oa = client or OpenAlex()
    errors: list[str] = []

    # Rung 1: a cited ORCID id is certain -- no LLM needed.
    try:
        source = resolve_via_source_link(expert, client=oa)
    except Exception as exc:  # noqa: BLE001 - resolver is best-effort
        logger.exception("source-link resolution failed")
        errors.append(f"resolve: {exc}")
        source = None
    if source:
        return source, None, errors

    # Gather name candidates (scoped to the resolved institution when possible).
    try:
        candidates = gather_name_candidates(expert, client=oa)
    except Exception as exc:  # noqa: BLE001 - resolver is best-effort
        logger.exception("name candidate gathering failed")
        errors.append(f"resolve: {exc}")
        candidates = NameCandidates()
    if candidates.error:
        errors.append(f"resolve: {candidates.error}")

    # Rung 2: accept directly only when name AND institution corroborate.
    top = confident_single(candidates.scored)
    if top is not None and candidates.scoped:
        return _resolution_from_candidate(top, candidates), None, errors

    # Rung 3: not confident -- the web-search disambiguator adjudicates. Called
    # even with no candidates, so it can look the expert up from scratch; it may
    # pick a candidate, report an identifier it found online, or abstain.
    disambiguation = disambiguate_author(expert, candidates.scored, llm=llm)
    if disambiguation.error:
        errors.append(f"disambiguate: {disambiguation.error}")

    if disambiguation.chosen:
        if disambiguation.confidence < LLM_CHOICE_MIN_CONFIDENCE:
            disambiguation.record = None
            disambiguation.name_score = 0.0
            return (
                AuthorResolution(
                    match_method="unresolved",
                    candidates_considered=candidates.candidates_considered,
                ),
                disambiguation,
                errors,
            )
        resolution = AuthorResolution(
            openalex_author_id=disambiguation.record.get("id"),
            display_name=disambiguation.record.get("display_name"),
            match_score=disambiguation.confidence,
            match_method="name-llm",
            candidates_considered=candidates.candidates_considered,
            record=disambiguation.record,
        )
        return resolution, disambiguation, errors

    # Rung 4: a web-discovered identifier, re-fetched and name-validated.
    if disambiguation.found_orcid or disambiguation.found_openalex_id:
        if disambiguation.confidence >= LLM_CHOICE_MIN_CONFIDENCE:
            resolution = _resolve_found_identifier(expert, disambiguation, client=oa)
            if resolution is not None:
                return resolution, disambiguation, errors

    # No confident match, and the disambiguator did not (or could not) pick one.
    resolution = AuthorResolution(
        match_method="unresolved",
        candidates_considered=candidates.candidates_considered,
    )
    return resolution, disambiguation, errors
