"""Tool composition for the notebook chat agent.

Assembles the toolset one chat turn runs with: the note read/edit tools
(scoped to the acting user's permissions), the OpenAlex literature tools, and
a web search. The OpenAlex toolset is reused minus ``submit_profile`` -- a
chat turn ends when the model answers in plain text, so a terminal submit
tool from another flow must not ride along.
"""

import logging

from research_ai.services.agent import Tool, Toolset
from research_ai.services.researcher_profile.openalex_tools import SUBMIT_PROFILE
from utils.brave_search import BraveSearch

logger = logging.getLogger(__name__)

_DEFAULT_MAX_SEARCHES = 8  # per-turn ceiling on web searches
_MAX_RESULTS = 5  # results surfaced to the model per call

_WEB_SEARCH_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "A focused web search query.",
        }
    },
    "required": ["query"],
}


class NotebookWebSearchToolset:
    """A single ``web_search`` tool over an injected search client.

    The concrete backend (a ``BraveSearch`` client by default) is injected so
    tests mock it, and the tool is inert -- present but returning an
    explanatory error -- until an API key is configured, so an unprovisioned
    deployment degrades rather than breaks. Providers that serve ``web_search``
    natively drop this tool at composition time.
    """

    def __init__(
        self,
        *,
        client: BraveSearch | None = None,
        max_searches: int = _DEFAULT_MAX_SEARCHES,
    ):
        self._client = client or BraveSearch()
        self.max_searches = max_searches
        self._searches_used = 0

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name="web_search",
                description=(
                    "Search the open web for facts outside the academic "
                    "literature -- news, datasets, tools, organizations, or "
                    "recent developments. Cite what you use so the user can "
                    "verify it. Limited to "
                    f"{self.max_searches} searches per turn."
                ),
                input_schema=_WEB_SEARCH_INPUT_SCHEMA,
                handler=self._web_search,
            )
        ]

    def _web_search(self, args: dict) -> dict:
        query = str((args or {}).get("query") or "").strip()
        if not query:
            return {"error": "query is required"}
        if not self._client.configured:
            return {
                "error": (
                    "Web search is not configured in this deployment. Answer "
                    "from the literature tools and what you already know."
                )
            }
        if self._searches_used >= self.max_searches:
            return {
                "error": (
                    f"Web search budget exhausted ({self.max_searches} "
                    "searches). Work from what you have already found."
                )
            }
        self._searches_used += 1
        results = self._client.search(query, count=_MAX_RESULTS)
        return {"query": query, "results": results}


def compose_notebook_toolset(
    *,
    note_toolset,
    openalex_toolset,
    web_search_toolset,
    native_tool_names: frozenset[str] = frozenset(),
) -> Toolset:
    """Note read/edit + OpenAlex literature + web search.

    ``native_tool_names`` are the names the provider runs server-side (on
    Claude Platform, ``web_search``). A local tool by that name is left out:
    the provider declares its own, and sending both would put two tools with
    one name in the request.
    """
    candidates = [
        tool for tool in openalex_toolset.build_tools() if tool.name != SUBMIT_PROFILE
    ]
    candidates.extend(web_search_toolset.build_tools())
    candidates.extend(note_toolset.build_tools())

    toolset = Toolset()
    for tool in candidates:
        if tool.name in native_tool_names:
            logger.info("provider serves %s server-side; local tool skipped", tool.name)
            continue
        toolset.add(tool)
    return toolset
