"""Brave web-search tool for the expert-finder agent.

Used to find professional contact pages (faculty directories, lab pages,
ORCID) after OpenAlex discovery. Results inform contact enrichment only --
they do not substitute for an OpenAlex author id.
"""

from __future__ import annotations

import logging

from research_ai.services.agent import Tool, Toolset
from utils.brave_search import BraveSearch

logger = logging.getLogger(__name__)

WEB_SEARCH = "web_search"

_DEFAULT_MAX_SEARCHES = 24  # per-run ceiling on contact web searches
_MAX_RESULTS = 5  # results surfaced to the model per call

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Contact-oriented query, e.g. "
                "'Jane Doe MIT faculty email' or "
                "'Ada Lovelace University College London ORCID'."
            ),
        }
    },
    "required": ["query"],
}


class ExpertFinderWebSearchToolset:
    """A single ``web_search`` tool over an injected Brave client.

    The backend is injected so tests mock it. When no API key is configured the
    tool stays registered but returns an explanatory error so the agent can
    fall back to other contact paths.
    """

    def __init__(
        self,
        *,
        client: BraveSearch | None = None,
        provenance: set[str] | None = None,
        max_searches: int = _DEFAULT_MAX_SEARCHES,
    ):
        self._client = client or BraveSearch()
        self.provenance = provenance if provenance is not None else set()
        self.max_searches = max_searches
        self._searches_used = 0

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name=WEB_SEARCH,
                description=(
                    "Search the open web for a researcher's professional "
                    "contact details: faculty/lab pages, departmental "
                    "directories, or ORCID. Prefer queries shaped as "
                    "`name + institution + email|faculty`. Do not invent "
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
                    "Web search is not configured in this deployment. Use "
                    "OpenAlex authorship and any preprint/corresponding-author "
                    "paths already available."
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
        results = self._client.search(query, count=_MAX_RESULTS)
        for result in results:
            url = str(result.get("url") or "").strip()
            if url:
                self.provenance.add(url)
        return {"query": query, "results": results}
