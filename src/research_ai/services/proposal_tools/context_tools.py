"""Read-only grounding tools for the proposal draft agent (no LLM).

A ``ProposalContextToolset`` resolves the whole proposal input from a single
``SearchExpert`` -- the RFP terms (via the grant on the expert search's unified
document) and the persisted researcher profile (via the expert). The tools only
read already-persisted data, so they hold ground truth the agent cannot invent.

Provenance: ``get_researcher_profile`` records each profile work's
``source_url``/``pdf_url`` into a shared set so a later citation-grounding stage
(PR6) can check a model-emitted citation against what the profile actually
contained. The set is supplied by the caller and shared across the proposal
toolsets for one run.
"""

import logging

from research_ai.services.agent import Tool, Toolset

logger = logging.getLogger(__name__)

# Tools that take no input still need a JSON Schema object for the provider.
_EMPTY_INPUT_SCHEMA = {"type": "object", "properties": {}}


class ProposalContextToolset:
    """RFP + researcher-profile grounding tools built from one ``SearchExpert``.

    Args:
        search_expert: The ``SearchExpert`` that resolves the whole input -- the
            ``Expert`` (profile) and, via ``expert_search.unified_document``, the
            ``Grant`` and GRANT post (RFP).
        provenance: Shared set of source/PDF URLs seen across the run.
            ``get_researcher_profile`` adds each profile work's URLs to it. A
            fresh set is created when omitted.
    """

    def __init__(self, search_expert, *, provenance: set[str] | None = None):
        self.search_expert = search_expert
        self.provenance = provenance if provenance is not None else set()

    # -- tool construction ------------------------------------------------

    def build_tools(self) -> list[Tool]:
        """Build the neutral core ``Tool`` objects backed by this toolset."""
        return [
            Tool(
                name="get_rfp_context",
                description=(
                    "Return the funder's RFP: the full call text plus the "
                    "structured grant terms (amount, currency, deadline, "
                    "organization, title). The proposal must directly answer "
                    "this and fit its dollars and timeline."
                ),
                input_schema=_EMPTY_INPUT_SCHEMA,
                handler=self._get_rfp_context,
            ),
            Tool(
                name="get_researcher_profile",
                description=(
                    "Return the persisted, source-attributed researcher profile "
                    "(resolution + selected works). The proposal's author "
                    "credibility must be grounded in this real track record; do "
                    "not claim work that is not here."
                ),
                input_schema=_EMPTY_INPUT_SCHEMA,
                handler=self._get_researcher_profile,
            ),
        ]

    def as_toolset(self) -> Toolset:
        """Wrap ``build_tools()`` in a core ``Toolset`` for the ``Agent``."""
        return Toolset(self.build_tools())

    # -- handlers ---------------------------------------------------------

    def _get_rfp_context(self, _args: dict) -> dict:
        unified_document = self.search_expert.expert_search.unified_document
        if unified_document is None:
            return {"error": "expert search has no unified document"}
        grant = unified_document.grants.first()
        if grant is None:
            return {"error": "no grant on the expert search's unified document"}
        return {
            "rfp_text": grant.get_llm_context_text(),
            "amount": str(grant.amount),
            "currency": grant.currency,
            "end_date": grant.end_date.isoformat() if grant.end_date else None,
            "organization": grant.organization,
            "short_title": grant.short_title,
        }

    def _get_researcher_profile(self, _args: dict) -> dict:
        profile = self.search_expert.expert.profile or {}
        for work in profile.get("works") or []:
            if not isinstance(work, dict):
                continue
            for key in ("source_url", "pdf_url"):
                url = str(work.get(key) or "").strip()
                if url:
                    self.provenance.add(url)
        return profile
