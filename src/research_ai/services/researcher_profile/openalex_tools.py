"""OpenAlex tool layer for the researcher-profile agent.

The agent owns *judgment* (which author is the expert, which works are worth
citing); these tools own *ground truth*. Every tool returns data read straight
from OpenAlex, so the agent can only select from real records -- it never
invents an author id, a DOI, or a PDF link.

``OpenAlexToolset`` exposes:

- ``tool_specs``  -- Converse ``toolSpec`` dicts to hand to the model
- ``dispatch``    -- runs a tool call and returns ``(result, stop)``

The toolset also records the ``source_url``/``pdf_url`` of every work it hands
back (``returned_source_urls`` / ``returned_pdf_urls``). The agent validates the
final profile against these sets so a hallucinated citation cannot survive.
"""

import logging

from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

# Terminal tool the model calls once to hand back the finished profile.
SUBMIT_PROFILE = "submit_profile"

_MAX_AUTHOR_CANDIDATES = 10  # author search results surfaced to the model
_MAX_ALTERNATIVES = 5
_MAX_INSTITUTIONS = 5
_MAX_TOPICS = 8
_MAX_WORKS_PER_CALL = 50  # ceiling on a single get_author_works fetch


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

    Best-effort: tool failures are returned to the model as ``{"error": ...}``
    rather than raised, so a transient miss does not abort the agent run.
    """

    def __init__(self, *, client: OpenAlex | None = None):
        self._oa = client or OpenAlex()
        # Provenance of every work URL handed to the model, for grounding.
        self.returned_source_urls: set[str] = set()
        self.returned_pdf_urls: set[str] = set()
        # Captured input of the terminal submit_profile call (None until called).
        self.submitted: dict | None = None

    # -- tool specs -------------------------------------------------------

    @property
    def tool_specs(self) -> list[dict]:
        return [
            {
                "toolSpec": {
                    "name": "search_institutions",
                    "description": (
                        "Search OpenAlex institutions by name. Use to turn an "
                        "affiliation string into an institution id that scopes "
                        "an author search."
                    ),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Affiliation / institution name.",
                                }
                            },
                            "required": ["query"],
                        }
                    },
                }
            },
            {
                "toolSpec": {
                    "name": "search_authors",
                    "description": (
                        "Search OpenAlex authors by name, optionally scoped to an "
                        "institution id. Returns candidate authors with their "
                        "institutions, topics, and citation counts so you can pick "
                        "the right person."
                    ),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "Author full name.",
                                },
                                "institution_id": {
                                    "type": "string",
                                    "description": (
                                        "Optional OpenAlex institution id to scope "
                                        "the search (from search_institutions)."
                                    ),
                                },
                            },
                            "required": ["name"],
                        }
                    },
                }
            },
            {
                "toolSpec": {
                    "name": "get_author",
                    "description": (
                        "Fetch one OpenAlex author by id or ORCID. Use to confirm a "
                        "candidate or to resolve an id/ORCID the expert already cites."
                    ),
                    "inputSchema": {
                        "json": {
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
                        }
                    },
                }
            },
            {
                "toolSpec": {
                    "name": "get_author_works",
                    "description": (
                        "List a resolved author's papers, most recent first. Only "
                        "works whose source_url/pdf_url appear here may be cited in "
                        "the profile."
                    ),
                    "inputSchema": {
                        "json": {
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
                                    "description": "Max works to return (default 25).",
                                },
                            },
                            "required": ["openalex_author_id"],
                        }
                    },
                }
            },
            {
                "toolSpec": {
                    "name": SUBMIT_PROFILE,
                    "description": (
                        "Submit the finished profile. Call exactly once when done. "
                        "Set resolution.openalex_author_id to null if you could not "
                        "confidently identify the author. Every work must be copied "
                        "from a get_author_works result."
                    ),
                    "inputSchema": {"json": _SUBMIT_INPUT_SCHEMA},
                }
            },
        ]

    # -- dispatch ---------------------------------------------------------

    def dispatch(self, name: str, tool_input: dict) -> tuple[dict, bool]:
        """Run a tool call. Returns ``(result, stop)``; ``stop`` ends the loop."""
        if name == SUBMIT_PROFILE:
            self.submitted = tool_input or {}
            return {"received": True}, True
        try:
            handler = {
                "search_institutions": self._search_institutions,
                "search_authors": self._search_authors,
                "get_author": self._get_author,
                "get_author_works": self._get_author_works,
            }.get(name)
            if handler is None:
                return {"error": f"unknown tool: {name}"}, False
            return handler(tool_input or {}), False
        except Exception as exc:  # noqa: BLE001 - tool errors go back to the model
            logger.info("OpenAlex tool %r failed: %s", name, exc)
            return {"error": str(exc)}, False

    # -- handlers ---------------------------------------------------------

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
        max_results = int(args.get("max_results") or 25)
        batch_size = max(1, min(max_results, _MAX_WORKS_PER_CALL))
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
                self.returned_source_urls.add(data["source_url"])
            if data["pdf_url"]:
                self.returned_pdf_urls.add(data["pdf_url"])
            payload.append(data)
        return {"works": payload}


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
    },
    "required": ["resolution"],
}
