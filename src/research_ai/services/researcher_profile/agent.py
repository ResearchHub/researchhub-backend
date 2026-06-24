"""The researcher-profile agent.

Replaces the old deterministic resolver/works pipeline. An LLM, given the
``OpenAlexToolset``, identifies the expert's OpenAlex author record and selects
their most relevant readable works -- the kind of judgment a hand-tuned name
matcher and recency sort did poorly. The tools guarantee every author id and
work URL is real; this module adds a grounding pass so a hallucinated citation
cannot reach the stored profile.

Built on the neutral agent core (``Agent``/``Toolset``/``LLMProvider``): the
agent drives a ``BedrockProvider`` over the OpenAlex tools, captures the
terminal ``submit_profile`` payload from the toolset, and grounds it.
"""

import json
import logging

from django.conf import settings
from django.utils import timezone

from research_ai.services.agent import AgentService, BedrockProvider, LLMProvider
from research_ai.services.researcher_profile.openalex_tools import OpenAlexToolset
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_MAX_WORKS = 5  # works kept on the profile after grounding
_DEFAULT_MAX_ITERATIONS = 12  # tool turns before the agent loop gives up

_SYSTEM_PROMPT = """\
You identify a researcher in OpenAlex and summarize their best work.

You are given an "expert" -- a name, an affiliation, an expertise blurb, and
source links that may contain an ORCID. The affiliation and expertise are
machine-generated and noisy; treat them as hints, not facts.

Goal: resolve the expert to the correct OpenAlex author, then pick up to five of
their most relevant, readable papers.

How to work:
- If a source link already gives an ORCID, confirm it with get_author before
  trusting it.
- Otherwise search_authors by name. Use search_institutions to turn the
  affiliation into an institution id and scope the search when names are common.
  Compare candidates' institutions, topics, and citation counts before choosing.
- Prefer missing over wrong: if no candidate is a confident match, submit with
  openalex_author_id = null and a low confidence.
- Once resolved, call get_author_works and choose up to five papers, favoring
  ones where this author is first/last author and that are recent and relevant.
  Only keep works that have a pdf_url (readable full text).

Grounding rule: every work you submit MUST come from a get_author_works result.
Only its source_url is used to look the work up -- copy that exactly and never
invent or edit a URL (the title and other fields are taken from the tool data,
so do not worry about reproducing them perfectly). Finish by calling
submit_profile exactly once.
"""


def _user_prompt(expert) -> str:
    payload = {
        "name": expert.full_name,
        "affiliation": getattr(expert, "affiliation", "") or "",
        "expertise": getattr(expert, "expertise", "") or "",
        "source_urls": expert.source_urls,
        "cited_orcid": expert.orcid,
    }
    return "Resolve this expert and build their profile:\n" + json.dumps(
        payload, indent=2, ensure_ascii=False
    )


def _ground_works(works, toolset: OpenAlexToolset) -> tuple[list[dict], list[str]]:
    """Materialize the selected works from ground truth.

    The model only chooses works by ``source_url``; each kept work is rebuilt
    from the record the tools actually returned, so a mangled or fabricated copy
    cannot reach the profile. Returns ``(kept_works, errors)``.
    """
    kept: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    if not isinstance(works, list):
        errors.append(
            f"submitted works was {type(works).__name__}, not a list; dropped"
        )
        works = []
    for work in works:
        source_url = (
            str(work.get("source_url") or "").strip() if isinstance(work, dict) else ""
        )
        if not source_url or source_url in seen:
            continue
        record = toolset.returned_works.get(source_url)
        if record is None:
            errors.append(f"dropped ungrounded work: {source_url!r}")
            continue
        seen.add(source_url)
        kept.append(
            {
                "title": str(record.get("title") or "").strip(),
                "publication_date": str(record.get("publication_date") or "").strip(),
                "publication_year": str(record.get("publication_year") or "").strip(),
                "source_url": source_url,
                "pdf_url": str(record.get("pdf_url") or "").strip(),
                "author_position": record.get("author_position"),
                "is_oa": bool(record.get("is_oa")),
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
    provider: LLMProvider | None = None,
    oa_client: OpenAlex | None = None,
) -> dict:
    """Run the agent and assemble the grounded profile dict.

    Best-effort: a failed run yields an unresolved profile with the error
    recorded, never raises.
    """
    errors: list[str] = []
    toolset = OpenAlexToolset(client=oa_client)
    provider = provider or BedrockProvider()
    max_iterations = getattr(
        settings, "RESEARCH_AI_AGENT_MAX_ITERATIONS", _DEFAULT_MAX_ITERATIONS
    )
    agent = AgentService(provider=provider, max_iterations=max_iterations).create_agent(
        toolset.as_toolset(), system_prompt=_SYSTEM_PROMPT
    )

    try:
        agent.run(_user_prompt(expert))
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
