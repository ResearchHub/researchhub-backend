"""LLM disambiguation: pick the right OpenAlex author among ambiguous candidates.

Only reached when the cheap name rungs are *not* confident -- several authors
clear the name bar, or the lone match is borderline (see
``resolver.confident_single``). The LLM weighs the expert's affiliation and
expertise against each candidate's institutions, topics, and output, and either
picks one or abstains. Abstaining (``choice = null``) is a first-class answer:
the builder then falls back to web search rather than guess.

The model never invents works -- it only chooses among real OpenAlex author
records, so the selected author's works are still fetched from OpenAlex. The
worst case is picking the wrong real author, which the conservative prompt and
abstain option are designed to avoid.
"""

import json
import logging
from dataclasses import dataclass

from research_ai.services.bedrock_llm_service import BedrockLLMService

logger = logging.getLogger(__name__)

_MAX_ALTERNATIVES = 5
_MAX_INSTITUTIONS = 4
_MAX_TOPICS = 6

_SYSTEM_PROMPT = (
    "You are a careful bibliometric author-disambiguation assistant. Given a "
    "researcher and a numbered list of candidate OpenAlex author records, decide "
    "which candidate, if any, is the SAME person as the researcher. Weigh the "
    "affiliation and field of study against each candidate's institutions, "
    "topics, and publication record. Author names are noisy and several people "
    "can share a name, so only choose a candidate you are confident is the same "
    "person. If no candidate clearly matches, abstain.\n\n"
    "Respond with ONLY a JSON object, no prose, of the form:\n"
    '{"choice": <candidate index, or null to abstain>, '
    '"confidence": <number 0..1>, "reasoning": "<one sentence>"}'
)


@dataclass
class DisambiguationResult:
    """Outcome of an LLM disambiguation pass.

    ``record`` is the chosen OpenAlex author entity (``None`` when the model
    abstained or the call failed). ``name_score`` is carried through from the
    chosen candidate so the builder can fold it into the match score.
    """

    record: dict | None = None
    name_score: float = 0.0
    confidence: float = 0.0
    reasoning: str = ""
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


def _parse_choice(raw: str, count: int) -> tuple[int | None, float, str]:
    """Parse the model's JSON reply into ``(choice, confidence, reasoning)``.

    Tolerates ```` ```json ```` fences and out-of-range/garbage choices, which
    are coerced to an abstain so a malformed reply never picks a wrong author.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text[:4].lower() == "json" else text
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model reply: {raw!r}")
    data = json.loads(text[start : end + 1])

    choice = data.get("choice")
    if not isinstance(choice, int) or not (0 <= choice < count):
        choice = None
    confidence = data.get("confidence")
    confidence = float(confidence) if isinstance(confidence, (int, float)) else 0.0
    reasoning = str(data.get("reasoning") or "")
    return choice, confidence, reasoning


def disambiguate_author(
    expert,
    scored: list[tuple[float, dict]],
    *,
    llm: BedrockLLMService | None = None,
) -> DisambiguationResult:
    """Ask the LLM to pick the matching author among ``scored`` candidates.

    Best-effort: any failure (no candidates, LLM error, unparseable reply) is
    returned as an abstain with ``error`` set, so the builder escalates to web
    search rather than raising.
    """
    if not scored:
        return DisambiguationResult()

    service = llm or BedrockLLMService()
    try:
        reply = service.invoke(_SYSTEM_PROMPT, _build_user_prompt(expert, scored))
        choice, confidence, reasoning = _parse_choice(reply, len(scored))
    except Exception as exc:  # noqa: BLE001 - disambiguation is best-effort
        logger.info("LLM disambiguation failed: %s", exc)
        return DisambiguationResult(error=str(exc))

    if choice is None:
        return DisambiguationResult(confidence=confidence, reasoning=reasoning)

    name_score, record = scored[choice]
    return DisambiguationResult(
        record=record,
        name_score=name_score,
        confidence=confidence,
        reasoning=reasoning,
    )
