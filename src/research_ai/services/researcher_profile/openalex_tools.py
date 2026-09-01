"""OpenAlex tool layer for the researcher-profile agent.

The agent owns *judgment* (which author is the expert, which works are worth
citing); these tools own *ground truth*. Every tool returns data read straight
from OpenAlex, so the agent can only select from real records -- it never
invents an author id, a DOI, or a PDF link.

``OpenAlexToolset`` builds neutral core ``Tool`` objects (the
``Tool``/``Toolset`` abstraction) rather than provider-specific Converse specs.
``build_tools()`` returns the list of ``Tool``s; ``as_toolset()`` wraps them in a
core ``Toolset`` ready to hand to an ``Agent``.

The toolset also retains the full ground-truth record of every work it hands
back, keyed by ``source_url`` (``returned_works``). The agent materializes the
final profile from these records so a hallucinated citation cannot survive.
"""

import logging
import re
from collections import Counter
from collections.abc import Callable
from math import log

from research_ai.services.agent import Tool, Toolset
from research_ai.services.pdf_text import (
    extract_text_from_pdf_bytes,
    get_pdf_bytes_from_url,
)
from utils.openalex import OpenAlex, Work

logger = logging.getLogger(__name__)

# Terminal tool the model calls once to hand back the finished profile.
SUBMIT_PROFILE = "submit_profile"

# The proposal agent's profile-scoped full-text tool name. Kept here as the
# shared composition constant; OpenAlex discovery exposes focused passage search.
GET_WORK_FULLTEXT = "get_work_fulltext"
GET_WORK_ABSTRACT = "get_work_abstract"
SEARCH_WORK_FULLTEXT = "search_work_fulltext"

_MAX_AUTHOR_CANDIDATES = 10  # author search results surfaced to the model
_MAX_ALTERNATIVES = 5
_MAX_INSTITUTIONS = 5
_MAX_TOPICS = 8
_MAX_WORKS_PER_CALL = 50  # ceiling on a single get_author_works fetch
_MAX_FULLTEXT_FETCHES = 6  # per-run ceiling on full-text reads
_MAX_FULLTEXT_SOURCE_CHARS = 120000
_MAX_PASSAGES = 5
_MAX_PASSAGE_CHARS = 1400
_MAX_FULLTEXT_QUERY_CHARS = 500
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")


def _institution_names(record: dict) -> list[str]:
    """Distinct institution display names for an author, most recent first."""
    names: list[str] = []
    for affiliation in record.get("affiliations") or []:
        institution = (affiliation or {}).get("institution") or {}
        name = (institution.get("display_name") or "").strip()
        if name and name not in names:
            names.append(name)
        if len(names) >= _MAX_INSTITUTIONS:
            break
    return names


def _author_view(record: dict) -> dict:
    """Compact, model-friendly projection of an OpenAlex author entity."""
    topics = [
        (topic.get("display_name") or "").strip()
        for topic in (record.get("topics") or [])
    ]
    return {
        "openalex_author_id": record.get("id"),
        "display_name": record.get("display_name"),
        "display_name_alternatives": (record.get("display_name_alternatives") or [])[
            :_MAX_ALTERNATIVES
        ],
        "orcid": record.get("orcid"),
        "institutions": _institution_names(record),
        "top_topics": [t for t in topics if t][:_MAX_TOPICS],
        "works_count": record.get("works_count"),
        "cited_by_count": record.get("cited_by_count"),
    }


class OpenAlexToolset:
    """OpenAlex-backed tools plus the terminal ``submit_profile`` tool.

    Best-effort: known tool failures are returned to the model as
    ``{"error": ...}`` rather than raised, and the core ``Toolset`` also catches
    any unexpected handler exception the same way, so a transient miss does not
    abort the agent run.
    """

    def __init__(
        self,
        *,
        client: OpenAlex | None = None,
        pdf_text_fetcher: Callable[[str], str] | None = None,
        max_fulltext_fetches: int = _MAX_FULLTEXT_FETCHES,
    ):
        self._oa = client or OpenAlex()
        self._pdf_text_fetcher = pdf_text_fetcher or self._fetch_pdf_text
        self._max_fulltext_fetches = max_fulltext_fetches
        self._fulltext_fetches_used = 0
        self._fulltext_cache: dict[str, str] = {}
        # Full ground-truth work record for every work handed to the model,
        # keyed by source_url. The profile is materialized from these rather
        # than from the model's (often mangled) copy of each work.
        self.returned_works: dict[str, dict] = {}
        # Captured input of the terminal submit_profile call (None until called).
        self.submitted: dict | None = None

    # -- tool construction ------------------------------------------------

    def build_tools(self) -> list[Tool]:
        """Build the neutral core ``Tool`` objects backed by this toolset."""
        return [
            Tool(
                name="search_institutions",
                description=(
                    "Search OpenAlex institutions by name. Use to turn an "
                    "affiliation string into an institution id that scopes an "
                    "author search."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Affiliation / institution name.",
                        }
                    },
                    "required": ["query"],
                },
                handler=self._search_institutions,
            ),
            Tool(
                name="search_authors",
                description=(
                    "Search OpenAlex authors by name, optionally scoped to an "
                    "institution id. Returns candidate authors with their "
                    "institutions, topics, and citation counts so you can pick "
                    "the right person."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Author full name.",
                        },
                        "institution_id": {
                            "type": "string",
                            "description": (
                                "Optional OpenAlex institution id to scope the "
                                "search (from search_institutions)."
                            ),
                        },
                    },
                    "required": ["name"],
                },
                handler=self._search_authors,
            ),
            Tool(
                name="get_author",
                description=(
                    "Fetch one OpenAlex author by id or ORCID. Use to confirm a "
                    "candidate or to resolve an id/ORCID the expert already cites."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "openalex_author_id": {
                            "type": "string",
                            "description": "OpenAlex author id.",
                        },
                        "orcid": {
                            "type": "string",
                            "description": "Bare ORCID identifier.",
                        },
                    },
                },
                handler=self._get_author,
            ),
            Tool(
                name="get_author_works",
                description=(
                    "List a resolved author's papers as compact cards, most "
                    "recent first. Results are cursor-paginated; follow "
                    "next_cursor when the first page does not give adequate "
                    "candidate coverage. Fetch an abstract or search full text "
                    "separately for promising works. Only works whose source_url "
                    "appears here may be cited in the profile."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "openalex_author_id": {
                            "type": "string",
                            "description": "Author id to list works for.",
                        },
                        "open_access_only": {
                            "type": "boolean",
                            "description": (
                                "Restrict to open-access works (default true)."
                            ),
                        },
                        "max_results": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": _MAX_WORKS_PER_CALL,
                            "description": "Works per page (default 25, maximum 50).",
                        },
                        "cursor": {
                            "type": "string",
                            "description": (
                                "Opaque next_cursor from the prior page. Omit for "
                                "the first page."
                            ),
                        },
                    },
                    "required": ["openalex_author_id"],
                },
                handler=self._get_author_works,
            ),
            Tool(
                name=GET_WORK_ABSTRACT,
                description=(
                    "Fetch the abstract of one work returned by get_author_works. "
                    "Pass its source_url exactly. Use this inexpensive detail "
                    "read to screen candidate papers before searching full text."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "source_url": {
                            "type": "string",
                            "description": (
                                "The work's source_url, exactly as returned by "
                                "get_author_works."
                            ),
                        }
                    },
                    "required": ["source_url"],
                },
                handler=self._get_work_abstract,
            ),
            Tool(
                name=SEARCH_WORK_FULLTEXT,
                description=(
                    "Search the readable full text of a work returned by "
                    "get_author_works for a focused question, method, instrument, "
                    "model system, or finding. Returns only the most relevant "
                    "passages, never the whole paper. Does not substitute the "
                    "abstract when no PDF is readable; call get_work_abstract "
                    "separately. Limited to "
                    f"{self._max_fulltext_fetches} document fetches per run."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "source_url": {
                            "type": "string",
                            "description": (
                                "The work's source_url, exactly as returned by "
                                "get_author_works."
                            ),
                        },
                        "query": {
                            "type": "string",
                            "maxLength": _MAX_FULLTEXT_QUERY_CHARS,
                            "description": (
                                "Focused terms or question to locate in the paper."
                            ),
                        },
                        "max_passages": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": _MAX_PASSAGES,
                            "description": "Maximum passages to return (default 3).",
                        },
                    },
                    "required": ["source_url", "query"],
                },
                handler=self._search_work_fulltext,
            ),
            Tool(
                name=SUBMIT_PROFILE,
                description=(
                    "Submit the finished profile. Call exactly once when done. "
                    "Set resolution.openalex_author_id to null if you could not "
                    "confidently identify the author. Every work must be copied "
                    "from a get_author_works result, and every capability's "
                    "evidence must be source_urls from get_author_works results."
                ),
                input_schema=_SUBMIT_INPUT_SCHEMA,
                handler=self._submit_profile,
                is_terminal=True,
            ),
        ]

    def as_toolset(self) -> Toolset:
        """Wrap ``build_tools()`` in a core ``Toolset`` for the ``Agent``."""
        return Toolset(self.build_tools())

    # -- handlers ---------------------------------------------------------

    def _submit_profile(self, args: dict) -> dict:
        """Terminal tool: capture the submitted profile and end the run."""
        self.submitted = args or {}
        return {"received": True}

    def _search_institutions(self, args: dict) -> dict:
        query = str(args.get("query") or "").strip()
        if not query:
            return {"results": []}
        resp = self._oa.search_institutions(query)
        results = [
            {
                "id": inst.get("id"),
                "display_name": inst.get("display_name"),
                "country_code": inst.get("country_code"),
            }
            for inst in (resp or {}).get("results") or []
            if inst.get("id")
        ]
        return {"results": results[:_MAX_INSTITUTIONS]}

    def _search_authors(self, args: dict) -> dict:
        name = str(args.get("name") or "").strip()
        if not name:
            return {"results": []}
        institution_id = str(args.get("institution_id") or "").strip() or None
        resp = self._oa.search_authors_via_name(name, institution_id=institution_id)
        results = [
            _author_view(rec)
            for rec in (resp or {}).get("results") or []
            if rec.get("id")
        ]
        return {"results": results[:_MAX_AUTHOR_CANDIDATES]}

    def _get_author(self, args: dict) -> dict:
        author_id = str(args.get("openalex_author_id") or "").strip()
        orcid = str(args.get("orcid") or "").strip()
        if orcid:
            record = self._oa.get_author_via_orcid(orcid)
        elif author_id:
            record = self._oa.get_author(author_id)
        else:
            return {"error": "provide openalex_author_id or orcid"}
        if not record:
            return {"error": "author not found"}
        return _author_view(record)

    def _get_author_works(self, args: dict) -> dict:
        author_id = str(args.get("openalex_author_id") or "").strip()
        if not author_id:
            return {"error": "openalex_author_id is required"}
        try:
            max_results = self._bounded_integer(
                args.get("max_results"), default=25, minimum=1, maximum=50
            )
        except ValueError as exc:
            return {"error": str(exc)}
        cursor = str(args.get("cursor") or "").strip() or "*"
        open_access_only = args.get("open_access_only", True)
        raw_works, next_cursor = self._oa.get_works(
            openalex_author_id=author_id,
            next_cursor=cursor,
            batch_size=max_results,
            sort="publication_date:desc",
            open_access_only=bool(open_access_only),
        )
        payload = []
        for entity in raw_works or []:
            work = Work.from_openalex(entity, author_id=author_id)
            if work is None:
                continue
            data = work.as_dict()
            if data["source_url"]:
                self.returned_works[data["source_url"]] = data
            payload.append(self._work_card(data))
            if len(payload) >= max_results:
                break
        return {
            "works": payload,
            "next_cursor": next_cursor,
            "has_more": bool(next_cursor),
        }

    def _get_work_abstract(self, args: dict) -> dict:
        source_url = str((args or {}).get("source_url") or "").strip()
        if not source_url:
            return {"error": "source_url is required"}
        work = self.returned_works.get(source_url)
        if work is None:
            return {
                "error": (
                    "Unknown source_url -- it must match a work returned by "
                    "get_author_works."
                )
            }
        abstract = str(work.get("abstract") or "").strip()
        if not abstract:
            return {
                "source_url": source_url,
                "title": str(work.get("title") or "").strip(),
                "error": "No abstract is available for this work.",
            }
        return {
            "source_url": source_url,
            "title": str(work.get("title") or "").strip(),
            "abstract": abstract,
        }

    def _search_work_fulltext(self, args: dict) -> dict:
        source_url = str((args or {}).get("source_url") or "").strip()
        query = " ".join(str((args or {}).get("query") or "").split())
        if not source_url:
            return {"error": "source_url is required"}
        if not query:
            return {"error": "query is required"}
        if len(query) > _MAX_FULLTEXT_QUERY_CHARS:
            return {"error": f"query exceeds {_MAX_FULLTEXT_QUERY_CHARS} characters"}
        try:
            max_passages = self._bounded_integer(
                (args or {}).get("max_passages"),
                default=3,
                minimum=1,
                maximum=_MAX_PASSAGES,
            )
        except ValueError as exc:
            return {"error": str(exc)}

        work = self.returned_works.get(source_url)
        if work is None:
            return {
                "error": (
                    "Unknown source_url -- it must match a work returned by "
                    "get_author_works."
                )
            }
        text, error = self._fulltext(source_url, work)
        if error is not None:
            return error
        if not text:
            return {
                "source_url": source_url,
                "title": str(work.get("title") or "").strip(),
                "error": (
                    "No readable full text is available for this work. "
                    "Call get_work_abstract to inspect its abstract."
                ),
            }
        passages = self._relevant_passages(text, query, limit=max_passages)
        return {
            "source_url": source_url,
            "title": str(work.get("title") or "").strip(),
            "query": query,
            "searched_characters": len(text),
            "passages": passages,
            "match_count": len(passages),
        }

    def _fulltext(self, source_url: str, work: dict) -> tuple[str, dict | None]:
        if source_url in self._fulltext_cache:
            return self._fulltext_cache[source_url], None
        if self._fulltext_fetches_used >= self._max_fulltext_fetches:
            return "", {
                "error": (
                    "Full-text fetch budget exhausted "
                    f"({self._max_fulltext_fetches} documents). Work from text "
                    "already searched or from separately fetched abstracts."
                )
            }
        pdf_url = str(work.get("pdf_url") or "").strip()
        if not pdf_url:
            self._fulltext_cache[source_url] = ""
            return "", None
        self._fulltext_fetches_used += 1
        text = self._pdf_text_fetcher(pdf_url)
        text = str(text or "").strip()
        self._fulltext_cache[source_url] = text
        return text, None

    @staticmethod
    def _work_card(work: dict) -> dict:
        return {
            "title": work.get("title"),
            "publication_date": work.get("publication_date"),
            "publication_year": work.get("publication_year"),
            "source_url": work.get("source_url"),
            "author_position": work.get("author_position"),
            "is_oa": bool(work.get("is_oa")),
            "has_abstract": bool(work.get("abstract")),
            "has_fulltext": bool(work.get("pdf_url")),
        }

    @staticmethod
    def _bounded_integer(value, *, default: int, minimum: int, maximum: int) -> int:
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("numeric bounds must be integers")
        if value < minimum or value > maximum:
            raise ValueError(f"numeric bound must be between {minimum} and {maximum}")
        return value

    @classmethod
    def _relevant_passages(cls, text: str, query: str, *, limit: int) -> list[dict]:
        """Rank overlapping text windows by focused lexical query coverage."""
        query_lower = query.lower()
        terms = cls._query_terms(query_lower)
        candidates = cls._passage_candidates(text, query_lower, terms)
        candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return cls._select_nonoverlapping_passages(candidates, limit=limit)

    @staticmethod
    def _query_terms(query_lower: str) -> list[str]:
        return list(dict.fromkeys(_WORD_RE.findall(query_lower)))

    @classmethod
    def _passage_candidates(
        cls, text: str, query_lower: str, terms: list[str]
    ) -> list[tuple[float, int, int, int, str]]:
        windows = cls._passage_windows(text)
        token_counts = [
            Counter(_WORD_RE.findall(passage.lower())) for *_, passage in windows
        ]
        document_frequency = Counter(
            term for counts in token_counts for term in terms if counts[term]
        )
        window_count = len(windows)
        candidates = []
        for (start, end, passage), counts in zip(windows, token_counts, strict=True):
            matched = [term for term in terms if counts[term]]
            score = sum(
                log(
                    1
                    + (window_count - document_frequency[term] + 0.5)
                    / (document_frequency[term] + 0.5)
                )
                * (counts[term] * 2.2 / (counts[term] + 1.2))
                for term in matched
            )
            if query_lower in passage.lower():
                score += 2
            if score:
                candidates.append((score, len(matched), start, end, passage))
        return candidates

    @staticmethod
    def _passage_windows(text: str) -> list[tuple[int, int, str]]:
        window_size = _MAX_PASSAGE_CHARS
        overlap = 240
        windows = []
        start = 0
        while start < len(text):
            end = min(start + window_size, len(text))
            if end < len(text):
                boundary = text.rfind(" ", start + window_size // 2, end)
                if boundary > start:
                    end = boundary
            passage = " ".join(text[start:end].split())
            windows.append((start, end, passage))
            if end >= len(text):
                break
            start = max(start + 1, end - overlap)
        return windows

    @staticmethod
    def _select_nonoverlapping_passages(
        candidates: list[tuple[float, int, int, int, str]], *, limit: int
    ) -> list[dict]:
        selected = []
        selected_ranges: list[tuple[int, int]] = []
        for score, _coverage, start, end, passage in candidates:
            if any(
                start < kept_end and end > kept_start
                for kept_start, kept_end in selected_ranges
            ):
                continue
            selected_ranges.append((start, end))
            selected.append(
                {
                    "start_char": start,
                    "end_char": end,
                    "score": round(score, 4),
                    "text": passage,
                }
            )
            if len(selected) >= limit:
                break
        return selected

    @staticmethod
    def _fetch_pdf_text(pdf_url: str) -> str:
        """Best-effort PDF text for a URL; ``""`` when unavailable or unreadable."""
        try:
            pdf_bytes = get_pdf_bytes_from_url(pdf_url)
            if not pdf_bytes:
                return ""
            return extract_text_from_pdf_bytes(
                pdf_bytes, max_chars=_MAX_FULLTEXT_SOURCE_CHARS
            )
        except Exception as exc:  # noqa: BLE001 - a bad PDF must not break the loop
            logger.warning(
                "search_work_fulltext: PDF read failed for %s: %s", pdf_url, exc
            )
            return ""


# JSON Schema for the terminal submit_profile tool's input. Mirrors the profile
# schema the agent assembles (built_at/errors are added server-side).
_WORK_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "publication_date": {"type": "string"},
        "publication_year": {"type": "string"},
        "source_url": {"type": "string"},
        "pdf_url": {"type": "string"},
        "author_position": {"type": ["string", "null"]},
        "is_oa": {"type": "boolean"},
    },
    "required": ["title", "source_url"],
}

# A lab capability the researcher's works evidence: a technique, instrument /
# platform, model system, or dataset the lab can actually work with. ``evidence``
# is the source_urls of the works that demonstrate it (grounded like ``works``).
_CAPABILITY_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["technique", "instrument", "model_system", "dataset"],
            "description": (
                "technique (assay/method), instrument (equipment/platform), "
                "model_system (organism/cell line/cohort), or dataset."
            ),
        },
        "name": {
            "type": "string",
            "description": "Short name, e.g. 'single-cell RNA-seq' or 'cryo-EM'.",
        },
        "note": {
            "type": "string",
            "description": (
                "One phrase on how the lab used it, grounded in the evidence works."
            ),
        },
        "evidence": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "source_urls of get_author_works works that demonstrate this "
                "capability. At least one; weight first/last-author works."
            ),
        },
    },
    "required": ["kind", "name", "evidence"],
}

_SUBMIT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "resolution": {
            "type": "object",
            "properties": {
                "openalex_author_id": {"type": ["string", "null"]},
                "display_name": {"type": ["string", "null"]},
                "orcid": {"type": ["string", "null"]},
                "confidence": {
                    "type": "number",
                    "description": "0..1 confidence the author was identified.",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Brief justification for the match (or non-match).",
                },
            },
            "required": ["openalex_author_id", "confidence"],
        },
        "works": {"type": "array", "items": _WORK_SCHEMA},
        "capabilities": {"type": "array", "items": _CAPABILITY_SCHEMA},
    },
    "required": ["resolution"],
}
