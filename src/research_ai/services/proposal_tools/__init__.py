"""Proposal-specific tools the draft agent calls.

Each tool is built to the agent-core ``Tool`` contract (``research_ai.services
.agent``): tools own ground truth and provenance, the agent owns judgment, and
deterministic code owns the gates. This package ships three toolsets plus the
judge wrapper:

- ``context_tools`` -- read-only RFP/profile grounding (no LLM).
- ``fulltext_tools`` -- on-demand full-text reads of the researcher's own works.
- ``web_search_tools`` -- research-only web search for facts outside the
  researcher's papers (grounds prose, not citations).
- ``verification_tools`` -- deterministic citation verification (the loop's
  external grounded signal).
- ``judge_tools`` -- a ``Tool`` wrapper over the multi-model judge panel
  (``research_ai.services.proposal_judge_panel``).

The draft driver wires these together; this package only builds the tools.
"""

from research_ai.services.proposal_tools.context_tools import (
    ProposalContextToolset,
)
from research_ai.services.proposal_tools.fulltext_tools import (
    ProposalFulltextToolset,
)
from research_ai.services.proposal_tools.judge_tools import build_judge_tool
from research_ai.services.proposal_tools.verification_tools import (
    ProposalVerificationToolset,
)
from research_ai.services.proposal_tools.web_search_tools import (
    ProposalWebSearchToolset,
)

__all__ = [
    "ProposalContextToolset",
    "ProposalFulltextToolset",
    "ProposalVerificationToolset",
    "ProposalWebSearchToolset",
    "build_judge_tool",
]
