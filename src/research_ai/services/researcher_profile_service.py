"""
Cold-start researcher profile builder for the proposal draft engine (Part 1).

The proposal draft engine starts from an ``Expert`` that has only names, an
``affiliation``, an ``expertise`` blurb, and a few ``sources`` URLs -- it has
*neither* an ORCID nor an OpenAlex id, so the existing
``researcher_external_context`` helpers (which key off a ResearchHub ``Author``)
cannot be called directly.

This module adds the net-new piece: a **resolver** that maps the ``Expert``
(known id links, else name + affiliation) to an OpenAlex author id (and ORCID
when findable), hands the resolved ids to the existing external-context
formatters, and falls back to OpenAI ``web_search`` for what OpenAlex/ORCID
can't supply (lab site, theses, talks, awards). The result is persisted **once**
on ``Expert.profile`` so the generate, verify, and notebook-iteration stages
reuse it instead of re-fetching.

**Every claim carries a source URL.** The ``claims`` list is the source-attributed
ground truth the draft's credibility (rubric #4) is built on and what the source
verifier (Part 3) later checks against -- entries without a real URL are dropped.

``Expert.profile`` schema (JSON, ``schema_version`` 1)::

    {
      "schema_version": 1,
      "built_at": "<ISO 8601>",
      "resolution": {
        "openalex_author_id": str | None,
        "orcid": str | None,
        "display_name": str | None,
        "match_score": float,                # 0..1
        "match_method": "source-link" | "name+affiliation" | "name" | "unresolved",
        "candidates_considered": int,
      },
      "metrics": {                           # {} when unresolved / no stats
        "h_index", "i10_index", "two_year_mean_citedness",
        "works_count", "cited_by_count", "source_url",
      },
      "affiliations": [str, ...],            # OpenAlex institutions
      "topics": [str, ...],                  # OpenAlex topics / concepts
      "works": [                             # first/last-author papers outrank
        {"title", "year", "source_url",      # middle ones, then most recent first;
         "author_position"},                 # "first" | "middle" | "last" | None
        ...,                                 # (None when ORCID is the source)
      ],
      "web_findings": [{"text", "url"}, ...],            # OpenAI web_search
      "claims": [{"text", "url"}, ...],      # flat, every entry has a URL
      "context_text": str,                   # prompt-ready block for the generator
      "errors": [str, ...],                  # non-fatal failures, for auditability
    }
"""

import logging
import re
import unicodedata
from dataclasses import dataclass

from django.utils import timezone

from research_ai.services.expert_finder_json import ExpertFinderJson
from research_ai.services.openai_expert_finder_service import OpenAIExpertFinderService
from research_ai.services.researcher_external_context import (
    fetch_openalex_author_record,
    fetch_orcid_works,
    format_openalex_author_record,
)
from research_ai.utils import trimmed_str
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1
_MAX_WORKS = 5  # papers kept on the profile (first/last author, then recency)
_WORKS_PAGE_SIZE = 50  # recent-works window fetched from OpenAlex before selection
_MAX_WEB_FINDINGS = 12
_MAX_AFFILIATIONS = 8
_MAX_TOPICS = 10
_CONTEXT_MAX_CHARS = 8000
_WEB_SEARCH_MAX_TOKENS = 4096

# Resolver thresholds. Deliberately conservative: a wrong match would attribute
# someone else's track record to the expert, which violates the "credit only a
# real track record / no unverified claim" bar. Tunable without code changes.
NAME_SCORE_STRONG = 0.6
AFFILIATION_MIN = 0.34

_AFFILIATION_STOPWORDS = {
    "a",
    "and",
    "centre",
    "center",
    "college",
    "de",
    "department",
    "dept",
    "des",
    "division",
    "du",
    "faculty",
    "for",
    "institut",
    "institute",
    "la",
    "lab",
    "laboratory",
    "national",
    "of",
    "research",
    "school",
    "state",
    "the",
    "universidad",
    "universite",
    "university",
}

_ORCID_RE = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dxX])")
_OPENALEX_AUTHOR_RE = re.compile(r"openalex\.org/(A\d+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------
def _norm(value: str) -> str:
    """Lowercase, strip accents, collapse to ``[a-z0-9 ]`` tokens."""
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9\s]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _affiliation_tokens(value: str) -> set[str]:
    return {t for t in _norm(value).split() if t and t not in _AFFILIATION_STOPWORDS}


def _is_http_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _bare_orcid(value: str | None) -> str | None:
    if not value:
        return None
    s = str(value).strip()
    if "orcid.org/" in s:
        s = s.split("orcid.org/", 1)[-1]
    return s.strip().strip("/").upper() or None


def _search_name(expert) -> str:
    parts = [
        getattr(expert, "first_name", ""),
        getattr(expert, "middle_name", ""),
        getattr(expert, "last_name", ""),
    ]
    return " ".join(str(p).strip() for p in parts if p and str(p).strip()).strip()


def _source_urls(expert) -> list[str]:
    urls: list[str] = []
    for item in getattr(expert, "sources", None) or []:
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip()
        elif isinstance(item, str):
            url = item.strip()
        else:
            url = ""
        if url:
            urls.append(url)
    return urls


# ---------------------------------------------------------------------------
# Resolver: Expert -> OpenAlex author id (+ ORCID)
# ---------------------------------------------------------------------------
@dataclass
class AuthorResolution:
    openalex_author_id: str | None = None
    orcid: str | None = None
    display_name: str | None = None
    match_score: float = 0.0
    match_method: str = "unresolved"
    candidates_considered: int = 0
    record: dict | None = None  # raw OpenAlex author entity; not serialized
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "openalex_author_id": self.openalex_author_id,
            "orcid": self.orcid,
            "display_name": self.display_name,
            "match_score": round(self.match_score, 3),
            "match_method": self.match_method,
            "candidates_considered": self.candidates_considered,
        }


def _extract_ids_from_sources(expert) -> tuple[str | None, str | None]:
    """Mine an ORCID and/or OpenAlex author id from the expert's ``sources`` URLs."""
    orcid: str | None = None
    oa_id: str | None = None
    for url in _source_urls(expert):
        low = url.lower()
        if orcid is None and "orcid.org" in low:
            m = _ORCID_RE.search(url)
            if m:
                orcid = m.group(1).upper()
        if oa_id is None:
            m = _OPENALEX_AUTHOR_RE.search(url)
            if m:
                oa_id = m.group(1)
    return orcid, oa_id


def _candidate_institution_names(record: dict) -> list[str]:
    names: list[str] = []
    for inst in record.get("last_known_institutions") or []:
        dn = (inst or {}).get("display_name")
        if dn:
            names.append(dn)
    lki = record.get("last_known_institution") or {}
    if lki.get("display_name"):
        names.append(lki["display_name"])
    for aff in record.get("affiliations") or []:
        inst = (aff or {}).get("institution") or {}
        if inst.get("display_name"):
            names.append(inst["display_name"])
    return names


def _name_score(expert, record: dict) -> float:
    """0..1 confidence the candidate's name matches the expert's."""
    first = _norm(getattr(expert, "first_name", ""))
    last = _norm(getattr(expert, "last_name", ""))
    if not last:
        return 0.0
    candidates = [record.get("display_name") or ""]
    candidates.extend(record.get("display_name_alternatives") or [])
    best = 0.0
    for cand in candidates:
        toks = _norm(cand).split()
        if not toks or last not in toks:
            continue
        if first and first in toks:
            best = max(best, 1.0 if toks[0] == first else 0.85)
        elif first and toks[0][:1] == first[:1]:
            best = max(best, 0.6)
        else:
            best = max(best, 0.3)
    return best


def _affiliation_score(expert, record: dict) -> float:
    """Fraction of the expert's affiliation tokens covered by the candidate's."""
    exp_tokens = _affiliation_tokens(getattr(expert, "affiliation", ""))
    if not exp_tokens:
        return 0.0
    cand_tokens: set[str] = set()
    for name in _candidate_institution_names(record):
        cand_tokens |= _affiliation_tokens(name)
    if not cand_tokens:
        return 0.0
    return len(exp_tokens & cand_tokens) / len(exp_tokens)


def _pick_best_candidate(expert, candidates: list[dict]) -> AuthorResolution:
    has_aff = bool(_affiliation_tokens(getattr(expert, "affiliation", "")))
    scored: list[tuple[float, float, dict]] = []
    for rec in candidates:
        ns = _name_score(expert, rec)
        if ns < NAME_SCORE_STRONG:
            continue
        scored.append((ns, _affiliation_score(expert, rec), rec))

    if not scored:
        return AuthorResolution(
            match_method="unresolved", candidates_considered=len(candidates)
        )

    # Affiliation overlap disambiguates first, then name strength, then prominence.
    scored.sort(
        key=lambda t: (t[1], t[0], t[2].get("cited_by_count") or 0), reverse=True
    )
    name_s, aff_s, record = scored[0]

    if has_aff and aff_s >= AFFILIATION_MIN:
        method = "name+affiliation"
    elif name_s >= 1.0 and len(scored) == 1:
        # A single, exact full-name match with nothing to disambiguate against.
        method = "name"
    else:
        return AuthorResolution(
            match_method="unresolved", candidates_considered=len(candidates)
        )

    score = (0.6 * name_s + 0.4 * aff_s) if has_aff else name_s
    return AuthorResolution(
        openalex_author_id=record.get("id"),
        orcid=_bare_orcid(record.get("orcid")),
        display_name=record.get("display_name"),
        match_score=score,
        match_method=method,
        candidates_considered=len(candidates),
        record=record,
    )


def resolve_openalex_author(
    expert, *, client: OpenAlex | None = None
) -> AuthorResolution:
    """
    Resolve an ``Expert`` to an OpenAlex author record (and ORCID when present).

    Prefers exact id links already in ``expert.sources``; otherwise searches by
    name and disambiguates by affiliation. Returns an unresolved result rather
    than guessing when confidence is low.
    """
    oa = client or OpenAlex()

    src_orcid, src_oa = _extract_ids_from_sources(expert)
    if src_orcid or src_oa:
        record = fetch_openalex_author_record(
            orcid_bare=src_orcid, openalex_author_ref=src_oa, client=oa
        )
        if record:
            return AuthorResolution(
                openalex_author_id=record.get("id")
                or (f"https://openalex.org/{src_oa}" if src_oa else None),
                orcid=_bare_orcid(record.get("orcid")) or src_orcid,
                display_name=record.get("display_name"),
                match_score=1.0,
                match_method="source-link",
                record=record,
            )
        if src_orcid:
            # We trust the explicit ORCID link even if the OpenAlex join missed.
            return AuthorResolution(
                orcid=src_orcid, match_score=1.0, match_method="source-link"
            )

    name = _search_name(expert)
    if not name:
        return AuthorResolution(match_method="unresolved")
    try:
        resp = oa.search_authors_via_name(name)
    except Exception as exc:  # noqa: BLE001 - network/parse errors are non-fatal
        logger.info("OpenAlex author search failed for %r: %s", name, exc)
        return AuthorResolution(match_method="unresolved", error=str(exc))

    return _pick_best_candidate(expert, resp.get("results") or [])


# ---------------------------------------------------------------------------
# Structured extractors (OpenAlex record + ORCID works)
# ---------------------------------------------------------------------------
def _extract_metrics(record: dict | None) -> dict:
    if not record:
        return {}
    ss = record.get("summary_stats") or {}
    metrics = {
        "h_index": ss.get("h_index"),
        "i10_index": ss.get("i10_index"),
        "two_year_mean_citedness": ss.get("2yr_mean_citedness"),
        "works_count": record.get("works_count"),
        "cited_by_count": record.get("cited_by_count"),
    }
    if all(v is None for v in metrics.values()):
        return {}
    metrics["source_url"] = record.get("id")
    return metrics


def _extract_affiliations(record: dict | None) -> list[str]:
    if not record:
        return []
    out: list[str] = []
    for name in _candidate_institution_names(record):
        name = (name or "").strip()
        if name and name not in out:
            out.append(name)
        if len(out) >= _MAX_AFFILIATIONS:
            break
    return out


def _extract_topics(record: dict | None) -> list[str]:
    if not record:
        return []
    out: list[str] = []
    for source in (record.get("topics") or [], record.get("x_concepts") or []):
        for item in source:
            label = ((item or {}).get("display_name") or "").strip()
            if label and label not in out:
                out.append(label)
            if len(out) >= _MAX_TOPICS:
                return out
        if out:
            break
    return out


def _orcid_work_url(work_summary: dict) -> str | None:
    ext = (work_summary.get("external-ids") or {}).get("external-id") or []
    for entry in ext:
        if str(entry.get("external-id-type") or "").lower() == "doi":
            doi = str(entry.get("external-id-value") or "").strip()
            if doi:
                return f"https://doi.org/{doi}"
    url = (work_summary.get("url") or {}).get("value")
    url = str(url or "").strip()
    return url if _is_http_url(url) else None


def _work_year(work: dict) -> int:
    try:
        return int(work.get("year") or 0)
    except (TypeError, ValueError):
        return 0


def _work_label(work: dict) -> str:
    label = f"({work['year']}) {work['title']}" if work.get("year") else work["title"]
    position = work.get("author_position")
    if position in ("first", "last"):
        label += f" [{position} author]"
    return label


def _select_works(works: list[dict]) -> list[dict]:
    """Keep ``_MAX_WORKS``: first/last-author papers outrank middle, then recency."""

    def rank(work: dict) -> tuple[int, int]:
        lead = 1 if work.get("author_position") in ("first", "last") else 0
        return (lead, _work_year(work))

    return sorted(works, key=rank, reverse=True)[:_MAX_WORKS]


def _norm_openalex_id(value: str | None) -> str:
    s = str(value or "").strip().lower()
    if "openalex.org/" in s:
        s = s.split("openalex.org/", 1)[-1]
    return s.strip("/")


def _author_position(work: dict, author_id: str | None) -> str | None:
    """This author's position ("first" | "middle" | "last") on an OpenAlex work."""
    target = _norm_openalex_id(author_id)
    if not target:
        return None
    for authorship in work.get("authorships") or []:
        author = (authorship or {}).get("author") or {}
        if _norm_openalex_id(author.get("id")) == target:
            return authorship.get("author_position") or None
    return None


def _extract_openalex_works(results: list[dict], author_id: str | None) -> list[dict]:
    """Map OpenAlex work entities to profile works, with this author's position."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for work in results or []:
        title = str(work.get("display_name") or "").strip()
        if not title:
            continue
        year = str(work.get("publication_year") or "").strip()
        url = str(work.get("doi") or "").strip() or str(work.get("id") or "").strip()
        if not _is_http_url(url):
            continue
        key = (title.lower(), year)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "title": title,
                "year": year,
                "source_url": url,
                "author_position": _author_position(work, author_id),
            }
        )
    return out


def _extract_orcid_works(works_json: dict | None, orcid_url: str | None) -> list[dict]:
    """Fallback works source when OpenAlex has none (no authorship positions)."""
    collected: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for group in (works_json or {}).get("group") or []:
        for ws in group.get("work-summary") or []:
            tb = ws.get("title") or {}
            inner = tb.get("title") or {}
            title = str(inner.get("value") or tb.get("value") or "").strip()
            if not title:
                continue
            year = str(
                ((ws.get("publication-date") or {}).get("year") or {}).get("value")
                or ""
            ).strip()
            url = _orcid_work_url(ws) or orcid_url
            if not url:
                continue
            # A group lists the same work once per claiming source.
            key = (title.lower(), year)
            if key in seen:
                continue
            seen.add(key)
            collected.append(
                {
                    "title": title,
                    "year": year,
                    "source_url": url,
                    "author_position": None,  # not in ORCID work summaries
                }
            )
    return _select_works(collected)


# ---------------------------------------------------------------------------
# Web-search enrichment (OpenAI Responses API ``web_search``)
# ---------------------------------------------------------------------------
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
    lines = [f"Researcher: {_search_name(expert) or '(unknown)'}"]
    aff = (getattr(expert, "affiliation", "") or "").strip()
    if aff:
        lines.append(f"Affiliation: {aff}")
    expertise = (getattr(expert, "expertise", "") or "").strip()
    if expertise:
        lines.append(f"Stated expertise: {expertise}")
    src_urls = _source_urls(expert)
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
        if not text_val or not _is_http_url(url):
            continue
        key = (text_val.lower(), url.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"text": text_val, "url": url})
        if len(out) >= _MAX_WEB_FINDINGS:
            break
    return out


def _web_search_enrich(expert, known_context: str, *, service=None) -> list[dict]:
    svc = service or OpenAIExpertFinderService()
    raw = svc.invoke(
        _WEB_SEARCH_SYSTEM,
        _build_web_search_user_prompt(expert, known_context),
        max_tokens=_WEB_SEARCH_MAX_TOKENS,
        temperature=0.0,
    )
    return _parse_web_findings(raw)


# ---------------------------------------------------------------------------
# Claims + prompt-ready context assembly
# ---------------------------------------------------------------------------
def _build_claims(
    *,
    author_url: str | None,
    metrics: dict,
    affiliations: list[str],
    topics: list[str],
    works: list[dict],
    web_findings: list[dict],
) -> list[dict]:
    """Flatten every fact into ``{text, url}``; drop anything without a real URL."""
    claims: list[dict] = []

    def add(text: str, url: str | None) -> None:
        text = (text or "").strip()
        url = (url or "").strip()
        if text and _is_http_url(url):
            claims.append({"text": text, "url": url})

    if metrics:
        h, i10 = metrics.get("h_index"), metrics.get("i10_index")
        if h is not None or i10 is not None:
            add(f"OpenAlex h-index {h}, i10-index {i10}", author_url)
        wc, cbc = metrics.get("works_count"), metrics.get("cited_by_count")
        if wc is not None or cbc is not None:
            add(f"OpenAlex works_count {wc}, cited_by_count {cbc}", author_url)
    for name in affiliations:
        add(f"Affiliation (OpenAlex): {name}", author_url)
    if topics:
        add("Research topics (OpenAlex): " + ", ".join(topics[:8]), author_url)
    for work in works:
        add(_work_label(work), work.get("source_url"))
    for finding in web_findings:
        add(finding.get("text", ""), finding.get("url"))

    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for claim in claims:
        key = (claim["text"].lower(), claim["url"].lower())
        if key not in seen:
            seen.add(key)
            out.append(claim)
    return out


def _build_context_text(
    expert,
    resolution: AuthorResolution,
    record: dict | None,
    works_text: str,
    web_findings: list[dict],
    *,
    max_chars: int = _CONTEXT_MAX_CHARS,
) -> str:
    chunks: list[str] = []

    head = [f"Researcher profile: {_search_name(expert)}".rstrip(": ")]
    if resolution.openalex_author_id:
        head.append(f"OpenAlex author: {resolution.openalex_author_id}")
    if resolution.orcid:
        head.append(f"ORCID: {resolution.orcid}")
    chunks.append("\n".join(head))

    oa_text = format_openalex_author_record(record) if record else ""
    if oa_text.strip():
        chunks.append("--- OpenAlex (public author record) ---\n" + oa_text.strip())

    if works_text.strip():
        chunks.append(
            "--- Selected works (first/last-author papers prioritized) ---\n"
            + works_text.strip()
        )

    if web_findings:
        lines = [f"- {f['text']} ({f['url']})" for f in web_findings]
        chunks.append(
            "--- Additional background (web search, source-cited) ---\n"
            + "\n".join(lines)
        )

    text = "\n\n".join(c for c in chunks if c.strip()).strip()
    if len(text) > max_chars:
        return text[:max_chars] + "\n[TRUNCATED]"
    return text


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def build_expert_profile(
    expert,
    *,
    oa_client: OpenAlex | None = None,
    openai_service=None,
    use_web_search: bool = True,
) -> dict:
    """
    Build the source-attributed researcher profile for an ``Expert`` (no write).

    Resolver -> OpenAlex author record -> ORCID works -> OpenAI ``web_search``.
    Every stage is best-effort: failures are captured in ``errors`` and the
    profile is still returned with whatever was found.
    """
    errors: list[str] = []
    oa = oa_client or OpenAlex()
    try:
        resolution = resolve_openalex_author(expert, client=oa)
    except Exception as exc:  # noqa: BLE001 - resolver is best-effort
        logger.exception("resolve_openalex_author failed")
        resolution = AuthorResolution(match_method="unresolved")
        errors.append(f"resolve: {exc}")
    if resolution.error:
        errors.append(f"resolve: {resolution.error}")

    record = resolution.record
    metrics = _extract_metrics(record)
    affiliations = _extract_affiliations(record)
    topics = _extract_topics(record)

    # Works come from OpenAlex (it knows this author's position on each paper);
    # ORCID is the fallback when no OpenAlex works are found.
    works: list[dict] = []
    if resolution.openalex_author_id:
        try:
            results, _ = oa.get_works(
                openalex_author_id=resolution.openalex_author_id,
                batch_size=_WORKS_PAGE_SIZE,
                sort="publication_date:desc",
            )
            works = _select_works(
                _extract_openalex_works(results, resolution.openalex_author_id)
            )
        except Exception as exc:  # noqa: BLE001 - works listing is best-effort
            logger.info("OpenAlex works fetch failed: %s", exc)
            errors.append(f"openalex-works: {exc}")
    if not works and resolution.orcid:
        orcid_works_json: dict = {}
        try:
            orcid_works_json = fetch_orcid_works(orcid_bare=resolution.orcid)
        except Exception as exc:  # noqa: BLE001 - ORCID is best-effort
            logger.info("ORCID works fetch failed: %s", exc)
            errors.append(f"orcid: {exc}")
        works = _extract_orcid_works(
            orcid_works_json, f"https://orcid.org/{resolution.orcid}"
        )
    works_text = "\n".join(f"- {_work_label(w)}" for w in works)

    # Build the "known" block first so web search complements rather than repeats.
    known_context = _build_context_text(expert, resolution, record, works_text, [])

    web_findings: list[dict] = []
    if use_web_search:
        try:
            web_findings = _web_search_enrich(
                expert, known_context, service=openai_service
            )
        except Exception as exc:  # noqa: BLE001 - web search is best-effort
            logger.info("web_search enrichment failed: %s", exc)
            errors.append(f"web_search: {exc}")

    context_text = _build_context_text(
        expert, resolution, record, works_text, web_findings
    )
    claims = _build_claims(
        author_url=resolution.openalex_author_id,
        metrics=metrics,
        affiliations=affiliations,
        topics=topics,
        works=works,
        web_findings=web_findings,
    )

    return {
        "schema_version": _SCHEMA_VERSION,
        "built_at": timezone.now().isoformat(),
        "resolution": resolution.as_dict(),
        "metrics": metrics,
        "affiliations": affiliations,
        "topics": topics,
        "works": works,
        "web_findings": web_findings,
        "claims": claims,
        "context_text": context_text,
        "errors": errors,
    }


def build_and_store_expert_profile(expert, **kwargs) -> dict:
    """Build the profile and persist it on ``Expert.profile`` (built once, reused)."""
    profile = build_expert_profile(expert, **kwargs)
    expert.profile = profile
    expert.save(update_fields=["profile", "updated_date"])
    return profile
