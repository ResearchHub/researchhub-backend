"""LLM disambiguation: identify the right OpenAlex author, grounded by web search."""

import json
import logging
from dataclasses import dataclass

from research_ai.services.openai_llm_service import OpenAIWebSearchLLMService
from research_ai.utils import extract_json_object

logger = logging.getLogger(__name__)

_MAX_ALTERNATIVES = 5
_MAX_INSTITUTIONS = 4
_MAX_TOPICS = 6

_SYSTEM_PROMPT = (
    "You are a careful bibliometric author-disambiguation assistant. You are "
    "given a researcher and a numbered list of candidate OpenAlex author records "
    "(the list may be empty). Decide which candidate, if any, is the SAME person "
    "as the researcher. Weigh the affiliation and field of study against each "
    "candidate's institutions, topics, and publication record.\n\n"
    "You have a web_search tool. Use it when the candidates' institutions do not "
    "corroborate the researcher's affiliation (for example, the researcher may "
    "have recently moved and OpenAlex is stale), or when no candidate is given, "
    "to find the researcher online. Author names are noisy and several people "
    "can share a name, so only choose a candidate -- or report an identifier -- "
    "you are confident refers to the same person; otherwise abstain.\n\n"
    "Answer in exactly one of three ways:\n"
    "1. Pick a candidate by its index.\n"
    "2. If none of the candidates is the person but web search identifies them, "
    "report their ORCID iD (preferred) or OpenAlex author id.\n"
    "3. Abstain.\n\n"
    "Respond with ONLY a JSON object, no prose, of the form:\n"
    '{"choice": <candidate index, or null>, "orcid": <ORCID iD, or null>, '
    '"openalex_id": <OpenAlex author id or URL, or null>, '
    '"confidence": <number 0..1>, "reasoning": "<one sentence>"}'
)


@dataclass
class _Decision:
    """Parsed-and-validated LLM reply, before resolving against candidates."""

    choice: int | None = None
    orcid: str | None = None
    openalex_id: str | None = None
    confidence: float = 0.0
    reasoning: str = ""


@dataclass
class DisambiguationResult:
    """Outcome of an LLM disambiguation pass.

    ``record`` is the chosen OpenAlex author entity (``None`` when the model
    abstained, reported an identifier instead, or the call failed).
    ``found_orcid``/``found_openalex_id`` carry a web-discovered identifier the
    resolver must re-fetch and name-validate; set only when no candidate chosen.
    """

    record: dict | None = None
    name_score: float = 0.0
    confidence: float = 0.0
    reasoning: str = ""
    found_orcid: str | None = None
    found_openalex_id: str | None = None
    error: str | None = None

    @property
    def chosen(self) -> bool:
        return self.record is not None


def _institution_names(record: dict) -> list[str]:
    """Distinct institution names for a candidate, most-recent first."""
    names: list[str] = []
    for inst in record.get("last_known_institutions") or []:
        name = (inst or {}).get("display_name")
        if name and name not in names:
            names.append(name)
    for aff in record.get("affiliations") or []:
        name = ((aff or {}).get("institution") or {}).get("display_name")
        if name and name not in names:
            names.append(name)
    return names[:_MAX_INSTITUTIONS]


def _candidate_view(index: int, record: dict) -> dict:
    """Compact, LLM-friendly projection of an OpenAlex author record."""
    return {
        "index": index,
        "display_name": record.get("display_name"),
        "also_known_as": (record.get("display_name_alternatives") or [])[
            :_MAX_ALTERNATIVES
        ],
        "institutions": _institution_names(record),
        "top_topics": [
            t.get("display_name")
            for t in (record.get("topics") or [])[:_MAX_TOPICS]
            if t.get("display_name")
        ],
        "works_count": record.get("works_count"),
        "cited_by_count": record.get("cited_by_count"),
    }


def _build_user_prompt(expert, scored: list[tuple[float, dict]]) -> str:
    researcher = {
        "name": expert.full_name,
        "affiliation": getattr(expert, "affiliation", "") or "",
        "expertise": getattr(expert, "expertise", "") or "",
    }
    candidates = [_candidate_view(i, rec) for i, (_, rec) in enumerate(scored)]
    return (
        "Researcher:\n"
        + json.dumps(researcher, ensure_ascii=False)
        + "\n\nCandidates:\n"
        + json.dumps(candidates, ensure_ascii=False)
    )


def _clean_str(value) -> str | None:
    """Trimmed string, or ``None`` when empty/missing."""
    s = str(value or "").strip()
    return s or None


def _parse_decision(raw: str, count: int) -> _Decision:
    """Parse the model's JSON reply into a disambiguation decision.

    An out-of-range/garbage choice is coerced to ``None`` so a malformed reply
    never picks a wrong author.
    """
    data = extract_json_object(raw)

    choice = data.get("choice")
    if isinstance(choice, bool) or not isinstance(choice, int) or not (
        0 <= choice < count
    ):
        choice = None
    confidence = data.get("confidence")
    confidence = (
        float(confidence)
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
        else 0.0
    )
    return _Decision(
        choice=choice,
        orcid=_clean_str(data.get("orcid")),
        openalex_id=_clean_str(data.get("openalex_id")),
        confidence=max(0.0, min(1.0, confidence)),
        reasoning=str(data.get("reasoning") or ""),
    )


def disambiguate_author(
    expert,
    scored: list[tuple[float, dict]],
    *,
    llm: OpenAIWebSearchLLMService | None = None,
) -> DisambiguationResult:
    """Ask the LLM to identify the matching author, grounded by web search.

    ``scored`` may be empty -- the model is still asked to look the researcher up.
    Best-effort: any failure (LLM error, unparseable reply) is returned as an
    abstain with ``error`` set, so the resolver escalates rather than raising.
    """
    service = llm or OpenAIWebSearchLLMService()
    try:
        reply = service.invoke(_SYSTEM_PROMPT, _build_user_prompt(expert, scored))
        decision = _parse_decision(reply, len(scored))
    except Exception as exc:  # noqa: BLE001 - disambiguation is best-effort
        logger.info("LLM disambiguation failed: %s", exc)
        return DisambiguationResult(error=str(exc))

    if decision.choice is not None:
        name_score, record = scored[decision.choice]
        return DisambiguationResult(
            record=record,
            name_score=name_score,
            confidence=decision.confidence,
            reasoning=decision.reasoning,
        )

    # No candidate chosen: may still carry a web-found identifier to verify.
    return DisambiguationResult(
        confidence=decision.confidence,
        reasoning=decision.reasoning,
        found_orcid=decision.orcid,
        found_openalex_id=decision.openalex_id,
    )
