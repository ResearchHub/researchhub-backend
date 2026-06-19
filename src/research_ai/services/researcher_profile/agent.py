"""The researcher-profile agent.

Replaces the old deterministic resolver/works pipeline. An LLM, given the
``OpenAlexToolset``, identifies the expert's OpenAlex author record and selects
their most relevant readable works -- the kind of judgment a hand-tuned name
matcher and recency sort did poorly. The tools guarantee every author id and
work URL is real; this module adds a grounding pass so a hallucinated citation
cannot reach the stored profile.
"""

import json
import logging

from research_ai.services.bedrock_llm_service import BedrockLLMService
from research_ai.services.researcher_profile.openalex_tools import OpenAlexToolset
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2
_MAX_WORKS = 5  # works kept on the profile after grounding

_SYSTEM_PROMPT = """\
You identify a researcher in OpenAlex and summarize their best work.

You are given an "expert" -- a name, an affiliation, an expertise blurb, and
source links that may contain an ORCID or OpenAlex author id. The affiliation
and expertise are machine-generated and noisy; treat them as hints, not facts.

Goal: resolve the expert to the correct OpenAlex author, then pick up to five of
their most relevant, readable papers.

How to work:
- If a source link already gives an ORCID or OpenAlex author id, confirm it with
  get_author before trusting it.
- Otherwise search_authors by name. Use search_institutions to turn the
  affiliation into an institution id and scope the search when names are common.
  Compare candidates' institutions, topics, and citation counts before choosing.
- Prefer missing over wrong: if no candidate is a confident match, submit with
  openalex_author_id = null and a low confidence.
- Once resolved, call get_author_works and choose up to five papers, favoring
  ones where this author is first/last author and that are recent and relevant.
  Only keep works that have a pdf_url (readable full text).

Grounding rule: every work you submit MUST be copied verbatim from a
get_author_works result -- same title, source_url, and pdf_url. Never invent or
edit a URL. Finish by calling submit_profile exactly once.
"""


def _user_prompt(expert) -> str:
    orcid, openalex_id = expert.source_ids
    payload = {
        "name": expert.full_name,
        "affiliation": getattr(expert, "affiliation", "") or "",
        "expertise": getattr(expert, "expertise", "") or "",
        "source_urls": expert.source_urls,
        "cited_orcid": orcid,
        "cited_openalex_author_id": openalex_id,
    }
    return "Resolve this expert and build their profile:\n" + json.dumps(
        payload, indent=2, ensure_ascii=False
    )


def _ground_works(
    works: list[dict], toolset: OpenAlexToolset
) -> tuple[list[dict], list[str]]:
    """Keep only works whose ``source_url`` the tools actually returned.

    Drops fabricated citations; blanks a ``pdf_url`` the tools never returned.
    Returns ``(kept_works, errors)``.
    """
    kept: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for work in works:
        if not isinstance(work, dict):
            continue
        source_url = str(work.get("source_url") or "").strip()
        if source_url not in toolset.returned_source_urls:
            errors.append(
                f"dropped ungrounded work: {work.get('title') or source_url!r}"
            )
            continue
        if source_url in seen:
            continue
        seen.add(source_url)
        pdf_url = str(work.get("pdf_url") or "").strip()
        if pdf_url and pdf_url not in toolset.returned_pdf_urls:
            pdf_url = ""  # never returned by a tool -> do not trust it
        kept.append(
            {
                "title": str(work.get("title") or "").strip(),
                "publication_date": str(work.get("publication_date") or "").strip(),
                "publication_year": str(work.get("publication_year") or "").strip(),
                "source_url": source_url,
                "pdf_url": pdf_url,
                "author_position": work.get("author_position"),
                "is_oa": bool(work.get("is_oa")),
            }
        )
        if len(kept) >= _MAX_WORKS:
            break
    return kept, errors


def _resolution(submitted: dict) -> dict:
    raw = submitted.get("resolution") if isinstance(submitted, dict) else None
    raw = raw or {}
    try:
        confidence = round(float(raw.get("confidence") or 0.0), 3)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "openalex_author_id": raw.get("openalex_author_id") or None,
        "display_name": raw.get("display_name") or None,
        "orcid": raw.get("orcid") or None,
        "confidence": max(0.0, min(1.0, confidence)),
        "reasoning": str(raw.get("reasoning") or "").strip(),
    }


def run_profile_agent(
    expert,
    *,
    llm: BedrockLLMService | None = None,
    oa_client: OpenAlex | None = None,
) -> dict:
    """Run the agent and assemble the grounded profile dict.

    Best-effort: a failed run yields an unresolved profile with the error
    recorded, never raises.
    """
    from django.utils import timezone

    errors: list[str] = []
    toolset = OpenAlexToolset(client=oa_client)
    service = llm or BedrockLLMService()

    try:
        service.run_tool_loop(
            _SYSTEM_PROMPT,
            _user_prompt(expert),
            tools=toolset.tool_specs,
            dispatch=toolset.dispatch,
        )
    except Exception as exc:  # noqa: BLE001 - agent run is best-effort
        logger.exception("researcher-profile agent failed")
        errors.append(f"agent: {exc}")

    if toolset.submitted is None:
        errors.append("agent: did not submit a profile")
        resolution = _resolution({})
        works: list[dict] = []
    else:
        resolution = _resolution(toolset.submitted)
        works, work_errors = _ground_works(
            toolset.submitted.get("works") or [], toolset
        )
        errors.extend(work_errors)

    return {
        "schema_version": SCHEMA_VERSION,
        "built_at": timezone.now().isoformat(),
        "resolution": resolution,
        "works": works,
        "errors": errors,
    }
