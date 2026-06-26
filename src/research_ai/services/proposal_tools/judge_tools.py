"""Core ``Tool`` wrapper over the multi-model judge panel.

The agent calls ``judge_proposal`` to get the panel's subjective verdict on a
draft -- absolute rubric scores (``mode="score"``) or an A-vs-B pick
(``mode="pairwise"``). The tool only delegates to ``ProposalJudgePanel``; the
panel never sees the deterministic programmatic gates, which stay external.
"""

from research_ai.services.agent import Tool
from research_ai.services.proposal_judge_panel import ProposalJudgePanel

_JUDGE_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "proposal": {
            "type": "string",
            "description": "The draft proposal to judge (candidate A in pairwise).",
        },
        "mode": {
            "type": "string",
            "enum": ["score", "pairwise"],
            "description": "score = absolute 1-5 rubric; pairwise = A-vs-B pick.",
        },
        "candidate_b": {
            "type": "string",
            "description": "The competing draft (B); required for pairwise mode.",
        },
    },
    "required": ["proposal"],
}


def build_judge_tool(panel: ProposalJudgePanel) -> Tool:
    """Build the ``judge_proposal`` tool delegating to ``panel``."""

    def handler(args: dict) -> dict:
        mode = str(args.get("mode") or "score").strip().lower()
        proposal = str(args.get("proposal") or "")
        if mode == "pairwise":
            candidate_b = str(args.get("candidate_b") or "")
            if not candidate_b:
                return {"error": "candidate_b is required for pairwise mode"}
            return {"winner": panel.pairwise(proposal, candidate_b)}
        return panel.score(proposal)

    return Tool(
        name="judge_proposal",
        description=(
            "Judge a draft proposal with the multi-model panel. mode='score' "
            "returns median rubric scores (c1..c7), an overall, and gaps; "
            "mode='pairwise' returns the winner ('A' or 'B') of proposal vs "
            "candidate_b."
        ),
        input_schema=_JUDGE_INPUT_SCHEMA,
        handler=handler,
    )
