"""Proposal-specific tools the draft agent calls.

Each tool is built to the agent-core ``Tool`` contract (``research_ai.services
.agent``): tools own ground truth and provenance, the agent owns judgment, and
deterministic code owns the gates. This package ships the toolsets plus the
sections assembler:

- ``context_tools`` -- read-only RFP/profile grounding (no LLM).
- ``fulltext_tools`` -- on-demand full-text reads of the researcher's own works.
- ``web_search_tools`` -- research-only web search for facts outside the
  researcher's papers (grounds prose, not citations).
- ``verification_tools`` -- deterministic citation verification (the loop's
  external grounded signal).
- ``assembly`` -- build the readable text + ProseMirror doc from the submitted
  sections (the panel scores every submit at the gate, not via an agent tool).

The draft driver wires these together; this package only builds the tools.
"""

from research_ai.services.proposal_tools.assembly import (
    PROPOSAL_SECTIONS,
    assemble_proposal,
)
from research_ai.services.proposal_tools.context_tools import (
    ProposalContextToolset,
)
from research_ai.services.proposal_tools.fulltext_tools import (
    ProposalFulltextToolset,
)
from research_ai.services.proposal_tools.verification_tools import (
    ProposalVerificationToolset,
)
from research_ai.services.proposal_tools.web_search_tools import (
    ProposalWebSearchToolset,
)

__all__ = [
    "PROPOSAL_SECTIONS",
    "ProposalContextToolset",
    "ProposalFulltextToolset",
    "ProposalVerificationToolset",
    "ProposalWebSearchToolset",
    "assemble_proposal",
]
