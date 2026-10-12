"""Brave ``web_search`` tool for expert-finder contact lookup.

Results are provenance URLs the agent may cite; they do not substitute for an
OpenAlex author id.
"""

from __future__ import annotations

from collections.abc import Callable

from research_ai.services.agent import Tool, Toolset
from utils.brave_search import BraveSearch

WEB_SEARCH = "web_search"

_DEFAULT_MAX_SEARCHES = 80  # per-run ceiling
_MAX_RESULTS = 5  # results surfaced to the model per call

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Search query for a researcher's professional contact, e.g. "
                "'Jane Doe MIT faculty email' or "
                "'Ada Lovelace University College London ORCID'."
            ),
        },
        "openalex_author_id": {
            "type": "string",
            "description": (
                "OpenAlex author id for the person being chased. Required to "
                "count toward the current search_works batch chase quota."
            ),
        },
    },
    "required": ["query"],
}


class ExpertFinderWebSearchToolset:
    """A single ``web_search`` tool over an injected Brave client."""

    def __init__(
        self,
        *,
        client: BraveSearch | None = None,
        provenance: set[str] | None = None,
        max_searches: int = _DEFAULT_MAX_SEARCHES,
        on_author_chased: Callable[[str | None], bool] | None = None,
    ):
        self._client = client or BraveSearch()
        self.provenance = provenance if provenance is not None else set()
        self.max_searches = max_searches
        self._searches_used = 0
        self._on_author_chased = on_author_chased

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name=WEB_SEARCH,
                description=(
                    "Search the open web for a researcher's professional "
                    "contact on faculty/lab/directory pages. Prefer "
                    '`"Name" "Institution" (email OR faculty) '
                    "-site:linkedin.com -site:researchgate.net`. Always pass "
                    "openalex_author_id so the chase counts toward unlocking "
                    "the next search_works page. Skip authors that already "
                    "have metadata_email — validate that first. Do not invent "
                    "emails from snippets alone -- copy only addresses that "
                    "clearly belong to the person, then call email_validate. "
                    f"Limited to {self.max_searches} searches per run."
                ),
                input_schema=_INPUT_SCHEMA,
                handler=self._web_search,
            )
        ]

    def as_toolset(self) -> Toolset:
        return Toolset(self.build_tools())

    def _web_search(self, args: dict) -> dict:
        query = str((args or {}).get("query") or "").strip()
        if not query:
            return {"error": "query is required"}
        if not self._client.configured:
            return {
                "error": (
                    "Web search is not configured in this deployment. Work "
                    "from OpenAlex authorship and contacts already found."
                )
            }
        if self._searches_used >= self.max_searches:
            return {
                "error": (
                    f"Web search budget exhausted ({self.max_searches} "
                    "searches). Work from contacts you have already found."
                )
            }
        self._searches_used += 1
        author_id = str((args or {}).get("openalex_author_id") or "").strip()
        counted = False
        if self._on_author_chased is not None and author_id:
            counted = bool(self._on_author_chased(author_id))
        results = self._client.search(query, count=_MAX_RESULTS)
        for result in results:
            url = str(result.get("url") or "").strip()
            if url:
                self.provenance.add(url)
        payload: dict = {"query": query, "results": results}
        if author_id:
            payload["openalex_author_id"] = author_id
            payload["counted_toward_batch_chase"] = counted
        elif self._on_author_chased is not None:
            payload["warning"] = (
                "Pass openalex_author_id so this chase counts toward the "
                "search_works batch quota."
            )
        return payload
