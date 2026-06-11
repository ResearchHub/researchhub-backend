"""LLM adjudication for ambiguous author matches.

When the deterministic resolver is left with several plausible OpenAlex
candidates (or a single non-exact one) it cannot safely pick from, a small LLM
call judges whether exactly one candidate is the expert. Conservative by
construction: any parse failure, out-of-range answer, or confidence below
``MIN_CONFIDENCE`` resolves to "no pick" -- never a guess.
"""

import logging

from research_ai.services.bedrock_llm_service import BedrockLLMService
from research_ai.services.expert_finder_json import ExpertFinderJson
from research_ai.services.researcher_profile.common import search_name, source_urls
from utils.openalex import author_institution_names

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.8
_MAX_CANDIDATES = 5
_MAX_TOKENS = 1024

_SYSTEM = (
    "You disambiguate researcher identities. Given a target researcher and a "
    "numbered list of candidate author records from OpenAlex, decide whether "
    "exactly ONE candidate is the same person.\n\n"
    "Rules:\n"
    "- Judge name (including variants and transliterations), institutions, and "
    "research topics together.\n"
    "- The target's details were machine-collected and may be stale or slightly "
    "wrong; allow for the researcher having moved institutions.\n"
    "- If no candidate clearly stands out, or two are comparably plausible, "
    "choose none. NEVER guess: a wrong match attributes someone else's "
    "publication record to this person.\n"
    "- Return STRICT JSON only, no prose, in exactly this shape:\n"
    '  {"candidate_index": <int or null>, "confidence": <0..1>, '
    '"reason": "<one sentence>"}'
)


def _candidate_block(index: int, record: dict) -> str:
    institutions = ", ".join(author_institution_names(record)[:3]) or "(none)"
    topics = ", ".join(
        label
        for t in (record.get("topics") or [])[:5]
        if (label := ((t or {}).get("display_name") or "").strip())
    )
    lines = [
        f"Candidate {index}: {record.get('display_name') or '(no name)'}",
        f"  Institutions: {institutions}",
    ]
    alternatives = ", ".join(record.get("display_name_alternatives") or [])
    if alternatives:
        lines.append(f"  Name variants: {alternatives}")
    if topics:
        lines.append(f"  Topics: {topics}")
    works_count = record.get("works_count")
    if works_count is not None:
        lines.append(f"  Works: {works_count}")
    return "\n".join(lines)


def _build_user_prompt(expert, records: list[dict]) -> str:
    lines = [f"Target researcher: {search_name(expert) or '(unknown)'}"]
    affiliation = (getattr(expert, "affiliation", "") or "").strip()
    if affiliation:
        lines.append(f"Affiliation (from our records): {affiliation}")
    expertise = (getattr(expert, "expertise", "") or "").strip()
    if expertise:
        lines.append(f"Expertise (from our records): {expertise}")
    urls = source_urls(expert)
    if urls:
        lines.append("Known links:")
        lines.extend(f"- {u}" for u in urls[:5])
    lines.append("")
    lines.append("Candidates:")
    lines.extend(_candidate_block(i, rec) for i, rec in enumerate(records))
    lines.append("")
    lines.append("Which candidate_index is the target researcher, if any?")
    return "\n".join(lines)


def pick_candidate(
    expert, records: list[dict], *, service=None
) -> tuple[dict | None, float]:
    """Ask the LLM to pick the matching record; ``(None, 0.0)`` when unsure."""
    records = records[:_MAX_CANDIDATES]
    if not records:
        return None, 0.0
    llm = service or BedrockLLMService()
    raw = llm.invoke(
        _SYSTEM,
        _build_user_prompt(expert, records),
        max_tokens=_MAX_TOKENS,
        temperature=0.0,
    )
    try:
        obj = ExpertFinderJson.parse_text(raw)
    except ValueError:
        logger.info("adjudication returned unparseable output")
        return None, 0.0
    if not isinstance(obj, dict):
        return None, 0.0
    index = obj.get("candidate_index")
    try:
        confidence = float(obj.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if (
        not isinstance(index, int)
        or isinstance(index, bool)
        or not 0 <= index < len(records)
        or confidence < MIN_CONFIDENCE
    ):
        return None, 0.0
    return records[index], confidence
