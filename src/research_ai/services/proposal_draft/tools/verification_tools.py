"""Citation grounding against OpenAlex -- the loop's external grounded signal.

Two sides of the same concern, both backed by the same OpenAlex client:

- ``search_works`` *finds* a real record (with its resolved DOI) for a
  field-level paper the agent knows by title but not by DOI, so the agent
  retrieves a citable work instead of guessing or hand-deriving a DOI.
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
from difflib import SequenceMatcher

from research_ai.services.agent import Tool, Toolset
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

# Normalized-title similarity bands (difflib ratio, 0..1).
_EXACT_TITLE = 0.92  # at/above: same title
_MINOR_TITLE = 0.6  # at/above (but below exact): same paper, drifted metadata

_MAX_WORK_RESULTS = 5  # candidate works surfaced per search_works call

_SEARCH_WORKS_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "The paper's title (or a descriptive query).",
        },
        "author": {
            "type": "string",
            "description": "Optional author name to disambiguate the search.",
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
                    "doi": {"type": "string"},
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
    authors = [
        str((a.get("author") or {}).get("display_name") or "").strip()
        for a in entity.get("authorships") or []
    ]
    return {
        "title": str(entity.get("display_name") or "").strip(),
        "authors": [a for a in authors if a],
        "year": entity.get("publication_year"),
        "source_url": str(entity.get("doi") or entity.get("id") or "").strip(),
    }


class ProposalVerificationToolset:
    """The deterministic ``verify_citations`` tool.

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
                name="search_works",
                description=(
                    "Find a published work by title (and optional author) to get "
                    "its real DOI for a field-level citation. Returns candidate "
                    "works with the resolved DOI (source_url), authors, and year "
                    "straight from OpenAlex. Use this to obtain a DOI you can "
                    "cite -- never invent or hand-derive one from a web result."
                ),
                input_schema=_SEARCH_WORKS_INPUT_SCHEMA,
                handler=self.search_works,
            ),
            Tool(
                name="verify_citations",
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
        title = str((args or {}).get("title") or "").strip()
        if not title:
            return {"error": "title is required"}
        author = str((args or {}).get("author") or "").strip()
        query = f"{title} {author}".strip()
        try:
            entities = self._oa.search_works(query, per_page=_MAX_WORK_RESULTS)
        except Exception as exc:  # noqa: BLE001 - a search miss is not fatal
            logger.info("OpenAlex works search failed for %r: %s", query, exc)
            return {"results": []}
        results = [
            _from_openalex(entity)
            for entity in entities or []
            if isinstance(entity, dict)
        ]
        results = [r for r in results if r["source_url"]]
        return {"results": results[:_MAX_WORK_RESULTS]}

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
        except Exception as exc:  # noqa: BLE001 - resolver miss is not fatal
            logger.info("OpenAlex DOI lookup failed for %r: %s", doi, exc)
            return None
        return _from_openalex(entity) if entity else None
