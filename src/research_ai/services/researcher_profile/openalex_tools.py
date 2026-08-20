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
from collections.abc import Callable

from research_ai.services.agent import Tool, Toolset
from research_ai.services.pdf_text import (
    extract_text_from_pdf_bytes,
    get_pdf_bytes_from_url,
)
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

# Terminal tool the model calls once to hand back the finished profile.
SUBMIT_PROFILE = "submit_profile"

# Name retained for the proposal agent's separate profile-scoped reader.
GET_WORK_FULLTEXT = "get_work_fulltext"
GET_WORK_ABSTRACT = "get_work_abstract"
SEARCH_WORK_FULLTEXT = "search_work_fulltext"

_MAX_AUTHOR_CANDIDATES = 10  # author search results surfaced to the model
_MAX_ALTERNATIVES = 5
_MAX_INSTITUTIONS = 5
_MAX_TOPICS = 8
_DEFAULT_WORKS_PER_CALL = 10
_MAX_WORKS_PER_CALL = 10  # compact metadata rows surfaced per call
_MAX_FULLTEXT_FETCHES = 4  # per-run ceiling on full-text searches
_MAX_PDF_SEARCH_CHARS = 120000  # searchable locally, never returned wholesale
_MAX_ABSTRACT_CHARS = 4000
_MAX_PASSAGES = 4
_MAX_PASSAGE_CHARS = 1500
_PASSAGE_OVERLAP_CHARS = 250
_QUERY_STOPWORDS = {
    "and",
    "for",
    "from",
    "into",
    "methods",
    "paper",
    "that",
    "the",
    "this",
    "using",
    "with",
}


def _work_metadata(work: dict) -> dict:
    """Compact list-row projection; abstracts are fetched separately."""
    return {
        key: work.get(key)
        for key in (
            "title",
            "publication_date",
            "publication_year",
            "source_url",
            "author_position",
            "pdf_url",
            "is_oa",
        )
    }


def _text_chunks(text: str) -> list[tuple[int, str]]:
    """Overlapping, word-aligned chunks suitable for local relevance ranking."""
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + _MAX_PASSAGE_CHARS)
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        chunk = " ".join(text[start:end].split())
        if chunk:
            chunks.append((start, chunk))
        if end >= len(text):
            break
        start = max(start + 1, end - _PASSAGE_OVERLAP_CHARS)
    return chunks


def _relevant_passages(text: str, query: str) -> list[dict]:
    terms = {
        term.lower()
        for term in re.findall(r"[\w-]{3,}", query)
        if term.lower() not in _QUERY_STOPWORDS
    }
    if not terms:
        terms = {term.lower() for term in re.findall(r"[\w-]{3,}", query)}
    phrase = " ".join(query.lower().split())
    ranked = []
    for start, chunk in _text_chunks(text):
        lowered = chunk.lower()
        matched_terms = sum(term in lowered for term in terms)
        occurrences = sum(lowered.count(term) for term in terms)
        score = (matched_terms * 10) + occurrences
        if phrase and phrase in lowered:
            score += 25
        if score:
            ranked.append((score, start, chunk))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = []
    for _score, start, chunk in ranked:
        if any(
            abs(start - item["start_char"])
            < (_MAX_PASSAGE_CHARS - _PASSAGE_OVERLAP_CHARS)
            for item in selected
        ):
            continue
        selected.append({"text": chunk, "start_char": start})
        if len(selected) >= _MAX_PASSAGES:
            break
    return selected


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
                    "List up to 10 compact paper metadata rows for a resolved "
                    "author, most recent first. Abstracts are intentionally "
                    "omitted; fetch one with get_work_abstract. Only "
                    "works whose source_url/pdf_url appear here may be cited in "
                    "the profile."
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
                            "description": "Max works to return (default 10, max 10).",
                        },
                    },
                    "required": ["openalex_author_id"],
                },
                handler=self._get_author_works,
            ),
            Tool(
                name=GET_WORK_ABSTRACT,
                description=(
                    "Fetch the abstract for one work returned by "
                    "get_author_works. Use for quick relevance checks before "
                    "spending a full-text search."
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
                    "Search one returned work's full text for a focused query "
                    "and return only the most relevant passages, not the whole "
                    "paper. Use for Methods, instruments, model systems, or "
                    "datasets after choosing a work from metadata/abstract. "
                    "Falls back to searching the abstract when no PDF is readable. "
                    "Limited to "
                    f"{self._max_fulltext_fetches} reads per run -- spend them "
                    "on the works that best evidence what the lab can do."
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
                            "description": (
                                "Focused terms to find, e.g. 'single-cell RNA-seq "
                                "methods and instruments'."
                            ),
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
            raw_max_results = args.get("max_results")
            requested = int(
                _DEFAULT_WORKS_PER_CALL if raw_max_results is None else raw_max_results
            )
        except (TypeError, ValueError):
            return {"error": "max_results must be an integer"}
        max_results = max(1, min(requested, _MAX_WORKS_PER_CALL))
        batch_size = max_results
        open_access_only = args.get("open_access_only", True)
        works = self._oa.get_works_typed(
            openalex_author_id=author_id,
            batch_size=batch_size,
            sort="publication_date:desc",
            open_access_only=bool(open_access_only),
        )
        payload = []
        for work in works[:max_results]:
            data = work.as_dict()
            if data["source_url"]:
                self.returned_works[data["source_url"]] = data
            payload.append(_work_metadata(data))
        return {"works": payload}

    def _returned_work(self, args: dict) -> tuple[str, dict | None, dict | None]:
        source_url = str((args or {}).get("source_url") or "").strip()
        if not source_url:
            return source_url, None, {"error": "source_url is required"}
        work = self.returned_works.get(source_url)
        if work is None:
            return (
                source_url,
                None,
                {
                    "error": (
                        "Unknown source_url -- it must match a work returned by "
                        "get_author_works."
                    )
                },
            )
        return source_url, work, None

    def _get_work_abstract(self, args: dict) -> dict:
        source_url, work, error = self._returned_work(args)
        if error:
            return error
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
            "abstract": abstract[:_MAX_ABSTRACT_CHARS],
            "truncated": len(abstract) > _MAX_ABSTRACT_CHARS,
        }

    def _search_work_fulltext(self, args: dict) -> dict:
        source_url, work, error = self._returned_work(args)
        if error:
            return error
        query = " ".join(str((args or {}).get("query") or "").split())
        if not query:
            return {"error": "query is required"}
        if self._fulltext_fetches_used >= self._max_fulltext_fetches:
            return {
                "error": (
                    "Full-text read budget exhausted "
                    f"({self._max_fulltext_fetches} reads). Work from the "
                    "abstracts already returned."
                )
            }
        self._fulltext_fetches_used += 1

        text = self._pdf_text_fetcher(str(work.get("pdf_url") or "").strip())
        content_type = "pdf"
        if not text:
            text = str(work.get("abstract") or "").strip()
            content_type = "abstract"
        if not text:
            return {
                "source_url": source_url,
                "content_type": "none",
                "error": "No readable full text or abstract available for this work.",
            }
        passages = _relevant_passages(text, query)
        return {
            "source_url": source_url,
            "title": str(work.get("title") or "").strip(),
            "content_type": content_type,
            "query": query,
            "passages": passages,
            "searched_chars": len(text),
            "message": None if passages else "No passages matched the query.",
        }

    @staticmethod
    def _fetch_pdf_text(pdf_url: str) -> str:
        """Best-effort PDF text for a URL; ``""`` when unavailable or unreadable."""
        try:
            pdf_bytes = get_pdf_bytes_from_url(pdf_url)
            if not pdf_bytes:
                return ""
            return extract_text_from_pdf_bytes(
                pdf_bytes, max_chars=_MAX_PDF_SEARCH_CHARS
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
