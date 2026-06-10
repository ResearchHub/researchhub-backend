"""Web-search enrichment via the OpenAI Responses API ``web_search`` tool.

Fills in what OpenAlex/ORCID can't supply (lab site, theses, talks, awards).
Findings without a real http(s) source URL are dropped.
"""

from research_ai.services.expert_finder_json import ExpertFinderJson
from research_ai.services.openai_expert_finder_service import OpenAIExpertFinderService
from research_ai.services.researcher_profile.common import (
    is_http_url,
    search_name,
    source_urls,
)
from research_ai.utils import trimmed_str

_MAX_WEB_FINDINGS = 12
_WEB_SEARCH_MAX_TOKENS = 4096

_WEB_SEARCH_SYSTEM = (
    "You are a meticulous research assistant compiling a verifiable professional "
    "background for a single named researcher. Use web search to find facts that "
    "are NOT already provided to you: lab or personal website, PhD "
    "dissertation/theses, invited talks, awards and honors, grants, notable "
    "software or datasets, editorial/society roles, and current position.\n\n"
    "Rules:\n"
    "- Every item MUST be backed by a specific source URL you actually found via "
    "search.\n"
    "- Do NOT invent facts or URLs. If you cannot find a real source, omit the "
    "item.\n"
    "- Prefer primary sources (institutional pages, the researcher's own site, "
    "ORCID, publisher pages) over aggregators.\n"
    "- Keep each item to one concise factual sentence.\n"
    "- Return STRICT JSON only, no prose, in exactly this shape:\n"
    '  {"findings": [{"text": "<one fact>", "url": "<https source url>"}]}'
)


def _build_web_search_user_prompt(expert, known_context: str) -> str:
    lines = [f"Researcher: {search_name(expert) or '(unknown)'}"]
    aff = (getattr(expert, "affiliation", "") or "").strip()
    if aff:
        lines.append(f"Affiliation: {aff}")
    expertise = (getattr(expert, "expertise", "") or "").strip()
    if expertise:
        lines.append(f"Expertise (from our records): {expertise}")
    src_urls = source_urls(expert)
    if src_urls:
        lines.append("Known source links:")
        lines.extend(f"- {u}" for u in src_urls[:10])
    if (known_context or "").strip():
        lines.append("")
        lines.append(
            "Already known (do NOT repeat; find additional, complementary background):"
        )
        lines.append(known_context.strip()[:4000])
    lines.append("")
    lines.append(f"Return up to {_MAX_WEB_FINDINGS} findings as strict JSON.")
    return "\n".join(lines)


def _parse_web_findings(raw: str) -> list[dict]:
    text = (raw or "").strip()
    if not text:
        return []
    try:
        obj = ExpertFinderJson.parse_text(text)
    except ValueError:
        return []
    items = obj.get("findings") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        text_val = trimmed_str(item.get("text", ""), max_len=500)
        url = trimmed_str(item.get("url", ""))
        if not text_val or not is_http_url(url):
            continue
        key = (text_val.lower(), url.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"text": text_val, "url": url})
        if len(out) >= _MAX_WEB_FINDINGS:
            break
    return out


def web_search_enrich(expert, known_context: str, *, service=None) -> list[dict]:
    svc = service or OpenAIExpertFinderService()
    raw = svc.invoke(
        _WEB_SEARCH_SYSTEM,
        _build_web_search_user_prompt(expert, known_context),
        max_tokens=_WEB_SEARCH_MAX_TOKENS,
        temperature=0.0,
    )
    return _parse_web_findings(raw)
