"""The researcher-profile agent.

Replaces the old deterministic resolver/works pipeline. An LLM, given the
``OpenAlexToolset``, identifies the expert's OpenAlex author record and selects
their most relevant readable works -- the kind of judgment a hand-tuned name
matcher and recency sort did poorly. The tools guarantee every author id and
work URL is real; this module adds a grounding pass so a hallucinated citation
cannot reach the stored profile.

Built on the neutral agent core (``Agent``/``Toolset``/``LLMProvider``): the
agent drives the settings-configured provider over the OpenAlex tools, captures
the terminal ``submit_profile`` payload from the toolset, and grounds it.
"""

import json
import logging

from django.utils import timezone

from research_ai.services.agent import AgentService, LLMProvider, resolve_provider
from research_ai.services.agent.errors import BudgetExceededError
from research_ai.services.researcher_profile.openalex_tools import OpenAlexToolset
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2  # v2 adds grounded lab capabilities
_MAX_WORKS = 5  # works kept on the profile after grounding
_MAX_CAPABILITIES = 12  # capabilities kept on the profile after grounding
_MAX_EVIDENCE_PER_CAPABILITY = 3  # evidence source_urls kept per capability
_VALID_CAPABILITY_KINDS = ("technique", "instrument", "model_system", "dataset")
_MAX_ITERATIONS = 16  # tool turns before the agent loop gives up

_SYSTEM_PROMPT = """\
You identify a researcher in OpenAlex and summarize their best work.

You are given an "expert" -- a name, an affiliation, an expertise blurb, and
source links that may contain an ORCID. The affiliation and expertise are
machine-generated and noisy; treat them as hints, not facts.

Goal: resolve the expert to the correct OpenAlex author, then pick their five
most relevant, readable papers.

How to work:
- If a source link already gives an ORCID, confirm it with get_author before
  trusting it.
- Otherwise search_authors by name. Use search_institutions to turn the
  affiliation into an institution id and scope the search when names are common.
  Compare candidates' institutions, topics, and citation counts before choosing.
- Prefer missing over wrong: if no candidate is a confident match, submit with
  openalex_author_id = null and a low confidence.
- Once resolved, call get_author_works and select five papers. Its listings are
  compact and cursor-paginated: follow next_cursor when the first page does not
  provide adequate candidates, and call get_work_abstract only for papers you
  are seriously considering. Strongly prefer
  ones where this author is first or last author; fall back to a middle-author
  paper only to reach five when there are not enough first/last ones. Among
  eligible papers, favor recent and relevant work. Only keep papers with a
  has_fulltext = true; aim for five, but return fewer rather than
  padding with papers that lack one.
- Then map the lab's capabilities. Call search_work_fulltext with focused
  Methods queries on the most relevant works (prefer first/last-author ones)
  for the concrete
  techniques, instruments/platforms, model systems, and datasets the lab
  actually works with -- the real bounds of what a proposal for this researcher
  could credibly do. Submit these as `capabilities`. A capability that appears
  only in a paper where the researcher is a middle author is the collaboration's,
  not necessarily this lab's -- include it only when the Methods make the lab's
  own hands-on role clear, and lean on first/last-author works. Prefer omitting
  a capability over asserting one the works do not clearly support.

Grounding rule: every work you submit MUST come from a get_author_works result,
and every capability's `evidence` MUST be source_urls of get_author_works
results. Only a work's source_url is used to look it up -- copy that exactly and
never invent or edit a URL (other fields are taken from the tool data, so do not
worry about reproducing them perfectly). Finish by calling submit_profile
exactly once.
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
                "abstract": str(record.get("abstract") or "").strip(),
            }
        )
        if len(kept) >= _MAX_WORKS:
            break
    return kept, errors


def _ground_capabilities(
    capabilities, toolset: OpenAlexToolset, valid_urls: set[str]
) -> tuple[list[dict], list[str]]:
    """Keep only capabilities whose evidence is grounded in returned works.

    Each capability's ``evidence`` is filtered to source_urls the tools actually
    returned (``valid_urls``); a capability with no grounded evidence left is
    dropped. This mirrors ``_ground_works``: the model's judgment of *what* a lab
    can do is kept, but every claim must point at a real paper. Returns
    ``(kept_capabilities, errors)``.
    """
    kept: list[dict] = []
    errors: list[str] = []
    if not isinstance(capabilities, list):
        if capabilities:
            errors.append(
                f"submitted capabilities was {type(capabilities).__name__}, "
                "not a list; dropped"
            )
        return kept, errors
    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        name = str(capability.get("name") or "").strip()
        kind = str(capability.get("kind") or "").strip()
        if not name or kind not in _VALID_CAPABILITY_KINDS:
            continue
        raw_evidence = capability.get("evidence")
        evidence: list[str] = []
        seen: set[str] = set()
        for url in raw_evidence if isinstance(raw_evidence, list) else []:
            url = str(url or "").strip()
            if url and url in valid_urls and url not in seen:
                seen.add(url)
                evidence.append(url)
            if len(evidence) >= _MAX_EVIDENCE_PER_CAPABILITY:
                break
        if not evidence:
            errors.append(f"dropped ungrounded capability: {name!r}")
            continue
        kept.append(
            {
                "kind": kind,
                "name": name,
                "note": str(capability.get("note") or "").strip(),
                "evidence": evidence,
            }
        )
        if len(kept) >= _MAX_CAPABILITIES:
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
    recorder=None,
) -> dict:
    """Run the agent and assemble the grounded profile dict.

    Best-effort: an ordinary failed run yields an unresolved profile with the
    error recorded. Budget exhaustion propagates so the owning loop workflow
    can stop before another provider call. The profile agent has no trace of
    its own unless the caller supplies a recorder.
    """
    errors: list[str] = []
    toolset = OpenAlexToolset(client=oa_client)
    provider = provider or resolve_provider()
    agent = AgentService(
        provider=provider, max_iterations=_MAX_ITERATIONS
    ).create_agent(
        toolset.as_toolset(), system_prompt=_SYSTEM_PROMPT, recorder=recorder
    )

    try:
        agent.run(_user_prompt(expert))
    except BudgetExceededError:
        raise
    except Exception as exc:  # noqa: BLE001 - agent run is best-effort
        logger.exception("researcher-profile agent failed")
        errors.append(f"agent: {exc}")

    if toolset.submitted is None:
        errors.append("agent: did not submit a profile")
        resolution = _resolution({})
        works: list[dict] = []
        capabilities: list[dict] = []
    else:
        resolution = _resolution(toolset.submitted)
        works, work_errors = _ground_works(
            toolset.submitted.get("works") or [], toolset
        )
        errors.extend(work_errors)
        capabilities, cap_errors = _ground_capabilities(
            toolset.submitted.get("capabilities"),
            toolset,
            set(toolset.returned_works),
        )
        errors.extend(cap_errors)

    return {
        "schema_version": SCHEMA_VERSION,
        "built_at": timezone.now().isoformat(),
        "resolution": resolution,
        "works": works,
        "capabilities": capabilities,
        "errors": errors,
    }
