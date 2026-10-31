"""Citation grounding against OpenAlex, shared by the proposal drafter and the chats.

Two sides of the same concern, both backed by the same OpenAlex client:

- ``search_works`` *finds* real records (each with its resolved DOI) by title
  or topic, so the agent retrieves a citable work instead of guessing or
  hand-deriving a DOI. It is hybrid: OpenAlex keyword and semantic (embedding)
  searches run side by side and their rankings are fused, so an exact title
  lookup and a plain-language topic query both land.
- ``verify_citations`` *checks* a DOI the agent already has.

The draft agent emits citations; ``verify_citations`` resolves each one against
ground truth (OpenAlex by DOI) and classifies how far the *claimed* metadata
drifts from the *resolved* record:

- ``exact``            -- title and authors match the resolved record.
- ``minor_drift``      -- same paper, but the claim drifted; carries the
                          corrected record so the caller can auto-correct from
                          source.
- ``major_fabrication`` -- the DOI resolves, but to a clearly different paper
                          (the model attached a real DOI to fabricated metadata,
                          or vice versa).
- ``dead``             -- the DOI resolves to nothing.

A model-emitted DOI is never trusted as proof of a claim: it is only a lookup
key, and the title/authors the model attached are checked against what that key
actually returns. ``dead`` and ``major_fabrication`` are the failures fed back to
revise; ``minor_drift`` is auto-corrected from the resolved record.

This stage is deterministic on purpose: it is the only fully external,
grounded signal in the otherwise self-referential draft/critique loop.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher

from research_ai.services.agent import Tool, Toolset
from utils.openalex import OpenAlex, work_author_names, work_venue
from utils.parsers import rebuild_sentence_from_inverted_index

logger = logging.getLogger(__name__)

SEARCH_WORKS = "search_works"
VERIFY_CITATIONS = "verify_citations"

# Normalized-title similarity bands (difflib ratio, 0..1).
_EXACT_TITLE = 0.92  # at/above: same title
_MINOR_TITLE = 0.6  # at/above (but below exact): same paper, drifted metadata

_MAX_WORK_RESULTS = 8  # candidate works surfaced per search_works call
_CANDIDATES_PER_SEARCH = 10  # works fetched from each of keyword and semantic
_RRF_K = 60  # reciprocal rank fusion damping (the standard constant)
_ABSTRACT_CHARS = 400  # abstract excerpt per result; get_work_abstract has it all
_RESULT_AUTHORS = 6  # author names listed per result; author_count has the total
# Years of slack around a requested range: OpenAlex often dates a paper by its
# online-first year, one off from the print year a citation carries.
_YEAR_SLACK = 1

# Citable work types; drops letters, errata, paratext, datasets and the like.
_WORK_TYPES = "article|review|preprint|book|book-chapter|report"
# Titles of replies and meeting-abstract records ("SUN-477 ...", "AB0403 ...")
# that survive the type filter; ranked below real papers, never dropped.
_REPLY_TITLE = re.compile(
    r"^(letter to the editor|response to|reply to|reply:|correspondence on|"
    r"comment on|erratum|correction to)",
    re.IGNORECASE,
)
_ABSTRACT_CODE_TITLE = re.compile(r"^[A-Z]{2,5}-?\d{3,5}\s")

_SEARCH_WORKS_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "The paper's title, or a topic described in plain "
            "words. Keep author names, years and journal names out of it; use "
            "the other fields.",
        },
        "author": {
            "type": "string",
            "description": "Optional author name (a surname is enough) to "
            "narrow the search.",
        },
        "year_from": {
            "type": "integer",
            "description": "Optional earliest publication year, inclusive.",
        },
        "year_to": {
            "type": "integer",
            "description": "Optional latest publication year, inclusive. Set "
            "both to the same year for a paper whose year you know; a year "
            "either side is included, since online and print years differ.",
        },
    },
    "required": ["title"],
}

_CITATIONS_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {
                        "type": "string",
                        "description": "Caller-assigned id linking the citation "
                        "to the claim it supports.",
                    },
                    "doi": {
                        "type": "string",
                        "description": "The DOI to resolve; a citation "
                        "without one is reported dead.",
                    },
                    "title": {"type": "string"},
                    "authors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Claimed author names.",
                    },
                },
                "required": ["claim_id"],
            },
        }
    },
    "required": ["citations"],
}


def _norm(text: object) -> str:
    """Lowercase, keep alphanumerics + spaces, collapse whitespace."""
    s = str(text or "").lower()
    kept = [ch if ch.isalnum() else " " for ch in s]
    return " ".join("".join(kept).split())


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _surname(name: object) -> str:
    """Last whitespace-delimited token of a name, normalized (handles 'Last, F.')."""
    raw = str(name or "").strip()
    if not raw:
        return ""
    head = raw.split(",")[0] if "," in raw else raw
    tokens = _norm(head).split()
    return tokens[-1] if tokens else ""


def _authors_match(claimed: list, resolved: list) -> bool:
    """At least half the claimed surnames appear among the resolved surnames.

    An empty claim cannot contradict the record, so it matches by default.
    """
    claimed_sur = {s for s in (_surname(a) for a in claimed) if s}
    if not claimed_sur:
        return True
    resolved_sur = {s for s in (_surname(a) for a in resolved) if s}
    if not resolved_sur:
        return False
    hits = sum(1 for s in claimed_sur if s in resolved_sur)
    return hits / len(claimed_sur) >= 0.5


def _from_openalex(entity: dict) -> dict:
    return {
        "title": str(entity.get("display_name") or "").strip(),
        "authors": work_author_names(entity),
        "year": entity.get("publication_year"),
        "venue": work_venue(entity),
        "source_url": str(entity.get("doi") or entity.get("id") or "").strip(),
    }


def _year(value: object) -> int | None:
    try:
        year = int(value)
    except TypeError, ValueError:
        return None
    return year if 1000 <= year <= 9999 else None


def _year_filter(year_from: int | None, year_to: int | None) -> str | None:
    """An OpenAlex ``publication_year`` filter value, or None for no bound.

    Each bound is widened by ``_YEAR_SLACK`` years.
    """
    if year_from and year_to:
        lo, hi = sorted((year_from, year_to))
        return f"{lo - _YEAR_SLACK}-{hi + _YEAR_SLACK}"
    if year_from:
        return f">{year_from - _YEAR_SLACK - 1}"
    if year_to:
        return f"<{year_to + _YEAR_SLACK + 1}"
    return None


def _abstract_excerpt(entity: dict) -> str:
    text = rebuild_sentence_from_inverted_index(
        entity.get("abstract_inverted_index") or {}
    )
    text = " ".join(str(text or "").split())
    if len(text) <= _ABSTRACT_CHARS:
        return text
    return text[:_ABSTRACT_CHARS].rsplit(" ", 1)[0] + " ..."


def _looks_like_reply(title: str) -> bool:
    title = title.strip()
    return bool(_REPLY_TITLE.match(title) or _ABSTRACT_CODE_TITLE.match(title))


def _fuse(rankings: list[list[dict]]) -> list[tuple[float, dict]]:
    """Reciprocal rank fusion of OpenAlex rankings, best first.

    A work's score is the sum of ``1 / (k + rank)`` over the rankings it
    appears in, so agreement between keyword and semantic search wins.
    """
    scores: dict[str, float] = {}
    works: dict[str, dict] = {}
    for ranking in rankings:
        for rank, work in enumerate(ranking, start=1):
            key = str(work.get("id") or work.get("doi") or "")
            if not key:
                continue
            scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + rank)
            works.setdefault(key, work)
    return sorted(
        ((score, works[key]) for key, score in scores.items()),
        key=lambda pair: -pair[0],
    )


def _search_result(entity: dict) -> dict | None:
    """A citable work as search_works returns it, or None without a DOI."""
    if not entity.get("doi"):  # semantic search cannot filter on DOI
        return None
    result = _from_openalex(entity)
    if not result["title"]:
        return None
    result["abstract"] = _abstract_excerpt(entity)
    return result


def _rank_works(fused: list[tuple[float, dict]], title: str, author: str) -> list:
    """The best ``_MAX_WORK_RESULTS`` results of a fused ranking.

    An exact title match ranks first, then works by ``author``, then fused
    score; replies and meeting abstracts rank last.
    """
    query_title = _norm(title)
    candidates = []
    for score, entity in fused:
        result = _search_result(entity)
        if result is None:
            continue
        exact = _similarity(query_title, _norm(result["title"])) >= _EXACT_TITLE
        by_author = bool(author) and _authors_match([author], result["authors"])
        if len(result["authors"]) > _RESULT_AUTHORS:
            result["author_count"] = len(result["authors"])
            result["authors"] = result["authors"][:_RESULT_AUTHORS]
        reply = _looks_like_reply(result["title"])
        candidates.append(((reply, not exact, not by_author, -score), result))
    candidates.sort(key=lambda pair: pair[0])

    # Reprints and duplicate records share title and year; keep the best.
    results, seen = [], set()
    for _, result in candidates:
        key = (_norm(result["title"]), result["year"])
        if key not in seen:
            seen.add(key)
            results.append(result)
    return results[:_MAX_WORK_RESULTS]


class CitationToolset:
    """The ``search_works`` and ``verify_citations`` tools.

    Args:
        oa_client: OpenAlex client (DOI resolution); defaults to a real one.
            Injected so tests mock the resolver.
    """

    def __init__(self, *, oa_client: OpenAlex | None = None):
        self._oa = oa_client or OpenAlex()

    # -- tool construction ------------------------------------------------

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name=SEARCH_WORKS,
                description=(
                    "Search OpenAlex for published works by title or by topic "
                    "described in plain words, optionally narrowed by author "
                    "and publication years. Keyword and semantic search run "
                    "together, so both an exact title and a description of "
                    f"the research work. Returns up to {_MAX_WORK_RESULTS} "
                    "relevance-ranked works, each with its resolved DOI "
                    "(source_url), authors, year, venue, and an abstract "
                    "excerpt straight from OpenAlex. Use this to find "
                    "literature and to get a real DOI you can cite -- never "
                    "invent or hand-derive one from a web result."
                ),
                input_schema=_SEARCH_WORKS_INPUT_SCHEMA,
                handler=self.search_works,
            ),
            Tool(
                name=VERIFY_CITATIONS,
                description=(
                    "Verify citations against ground truth. For each citation "
                    "(claim_id + doi/title/authors), resolve the DOI and classify "
                    "the claim as exact, minor_drift (corrected from source), "
                    "major_fabrication, or dead. Never trust the model's DOI as "
                    "proof -- it is only a lookup key."
                ),
                input_schema=_CITATIONS_INPUT_SCHEMA,
                handler=self.verify_citations,
            ),
        ]

    def as_toolset(self) -> Toolset:
        return Toolset(self.build_tools())

    # -- handlers ---------------------------------------------------------

    def search_works(self, args: dict) -> dict:
        args = args or {}
        title = str(args.get("title") or "").strip()
        if not title:
            return {"error": "title is required"}
        # Matching keeps the name as given ("Piaggio, G." reads surname-first);
        # commas separate OpenAlex filters, so none may reach the filter value.
        author = str(args.get("author") or "").strip()
        author_filter = " ".join(author.replace(",", " ").split())
        filters = {"type": _WORK_TYPES}
        years = _year_filter(_year(args.get("year_from")), _year(args.get("year_to")))
        if years:
            filters["publication_year"] = years
        # Semantic search takes no author filter; its works by the author are
        # ranked up instead.
        keyword_filters = (
            {**filters, "raw_author_name.search": author_filter}
            if author_filter
            else filters
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            keyword = pool.submit(self._search, title, False, keyword_filters)
            semantic = pool.submit(self._search, title, True, filters)
            rankings = [keyword.result(), semantic.result()]
        return {"results": _rank_works(_fuse(rankings), title, author)}

    def _search(self, query: str, semantic: bool, filters: dict) -> list[dict]:
        """One OpenAlex ranking; a failed search is an empty one, not fatal."""
        try:
            entities = self._oa.search_works(
                query,
                per_page=_CANDIDATES_PER_SEARCH,
                semantic=semantic,
                filters=filters,
            )
        except Exception as exc:
            mode = "semantic" if semantic else "keyword"
            logger.info("OpenAlex %s search failed for %r: %s", mode, query, exc)
            return []
        return [entity for entity in entities or [] if isinstance(entity, dict)]

    def verify_citations(self, args: dict) -> dict:
        citations = args.get("citations")
        if not isinstance(citations, list):
            return {"error": "citations must be a list"}

        results: list[dict] = []
        summary = {"dead": 0, "major": 0, "minor": 0}
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            result = self._verify_one(citation)
            results.append(result)
            if result["severity"] == "dead":
                summary["dead"] += 1
            elif result["severity"] == "major_fabrication":
                summary["major"] += 1
            elif result["severity"] == "minor_drift":
                summary["minor"] += 1
        return {"results": results, "summary": summary}

    # -- internals --------------------------------------------------------

    def _verify_one(self, citation: dict) -> dict:
        claim_id = citation.get("claim_id")
        resolved = self._resolve(citation.get("doi"))
        severity = self._classify(citation, resolved)
        result = {
            "claim_id": claim_id,
            "severity": severity,
            "resolved": resolved,
        }
        if severity == "minor_drift":
            # Auto-correct from the source record.
            result["correction"] = resolved
        return result

    def _classify(self, citation: dict, resolved: dict | None) -> str:
        if resolved is None:
            return "dead"
        claimed_title = _norm(citation.get("title"))
        authors_ok = _authors_match(citation.get("authors") or [], resolved["authors"])
        if not claimed_title:
            # No title claimed to contradict; only adopt when authors also match.
            return "minor_drift" if authors_ok else "major_fabrication"
        similarity = _similarity(claimed_title, _norm(resolved["title"]))
        if similarity >= _EXACT_TITLE and authors_ok:
            return "exact"
        if similarity >= _MINOR_TITLE and authors_ok:
            return "minor_drift"
        return "major_fabrication"

    def _resolve(self, doi: object) -> dict | None:
        doi = str(doi or "").strip()
        if not doi:
            return None
        try:
            entity = self._oa.get_work_by_doi(doi)
        except Exception as exc:  # a resolver miss is not fatal
            logger.info("OpenAlex DOI lookup failed for %r: %s", doi, exc)
            return None
        return _from_openalex(entity) if entity else None
