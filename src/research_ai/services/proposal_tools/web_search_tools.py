"""Web-search grounding tool for the proposal draft agent.

The OpenAlex/profile/fulltext tools ground the proposal in the researcher's own
literature; this one lets the agent reach the open web for facts that are not in
any paper -- a specific public dataset accession, a named collaborator, a funder
detail, competing work -- so it can replace the placeholders judges penalize
("an unnamed MS dataset", "a glial-biology colleague") with concrete, checkable
detail.

Scope is deliberately narrow. Results are **research-only**: they inform the
prose but are not academic citations. Formal citations stay DOI-backed and
OpenAlex-verified -- a web page has no DOI and would fail the citation gate. The
runner keeps this toolset's ``provenance`` **separate** from the
citation-grounding set on purpose, so a web URL can never satisfy the citation
gate even if the model tries to cite one. The system prompt tells the agent to
weave web findings into the text, not to submit them as ``citations``.

The concrete search backend (a ``BraveSearch`` client by default) is injected so
tests mock it, and the tool is inert -- present but returning an explanatory
error -- until an API key is configured, so an unprovisioned deployment degrades
rather than breaks.
"""

import logging

from research_ai.services.agent import Tool, Toolset
from utils.brave_search import BraveSearch

logger = logging.getLogger(__name__)

_DEFAULT_MAX_SEARCHES = 6  # per-run ceiling on web searches
_MAX_RESULTS = 5  # results surfaced to the model per call

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "A focused web search query, e.g. a public dataset name, a "
                "collaborator, or a funder detail you need to name concretely."
            ),
        }
    },
    "required": ["query"],
}


class ProposalWebSearchToolset:
    """A single ``web_search`` tool over an injected search client.

    Args:
        client: search client exposing ``configured`` and
            ``search(query, count)``; defaults to a real ``BraveSearch``.
        provenance: set of result URLs seen across the run, for
            inspection/telemetry. The runner passes a set that is NOT the
            citation-grounding provenance (web pages must never be citable). A
            fresh set is created when omitted.
        max_searches: per-run ceiling on searches (bounds cost and context).
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

    # -- tool construction ------------------------------------------------

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name="web_search",
                description=(
                    "Search the open web for facts not found in the researcher's "
                    "papers -- a specific public dataset accession, a named "
                    "collaborator, a funder detail, or competing work. Use it to "
                    "replace vague placeholders with concrete, checkable detail. "
                    "Results ground the prose only; they are NOT citations -- do "
                    "not put web URLs in the submit_proposal `citations` array, "
                    "which must stay DOI-backed. "
                    f"Limited to {self.max_searches} searches per run."
                ),
                input_schema=_INPUT_SCHEMA,
                handler=self._web_search,
            )
        ]

    def as_toolset(self) -> Toolset:
        """Wrap ``build_tools()`` in a core ``Toolset`` for the ``Agent``."""
        return Toolset(self.build_tools())

    # -- handler ----------------------------------------------------------

    def _web_search(self, args: dict) -> dict:
        query = str((args or {}).get("query") or "").strip()
        if not query:
            return {"error": "query is required"}
        if not self._client.configured:
            return {
                "error": (
                    "Web search is not configured in this deployment. Ground the "
                    "proposal in the profile and OpenAlex tools instead."
                )
            }
        if self._searches_used >= self.max_searches:
            return {
                "error": (
                    f"Web search budget exhausted ({self.max_searches} searches). "
                    "Work from what you have already found."
                )
            }
        self._searches_used += 1

        results = self._client.search(query, count=_MAX_RESULTS)
        for result in results:
            url = str(result.get("url") or "").strip()
            if url:
                self.provenance.add(url)
        return {"query": query, "results": results}
