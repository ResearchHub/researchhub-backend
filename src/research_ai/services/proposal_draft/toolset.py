"""Tool composition for the proposal-drafting agent.

Builds the terminal ``submit_proposal`` tool and assembles the full toolset
the agent runs with (OpenAlex + context + fulltext + web + verification +
judge + submit). The submit handler and the judge-context provider stay with the
runner -- they close over run state; this module owns only the static schema
and the wiring.
"""

from research_ai.services.agent import Tool, Toolset
from research_ai.services.proposal_tools import build_judge_tool
from research_ai.services.researcher_profile.openalex_tools import SUBMIT_PROFILE

SUBMIT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "hypothesis": {"type": "string"},
                "approach": {"type": "string"},
                "why_this_team": {"type": "string"},
                "scope_timeline": {"type": "string"},
            },
            "required": [
                "title",
                "hypothesis",
                "approach",
                "why_this_team",
                "scope_timeline",
            ],
        },
        "prosemirror": {
            "type": "object",
            "description": 'ProseMirror doc: {"type": "doc", "content": [...]}.',
        },
        "plain_text": {
            "type": "string",
            "description": "The full proposal as readable plain text.",
        },
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "doi": {"type": "string"},
                    "title": {"type": "string"},
                    "authors": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["claim_id"],
            },
        },
    },
    "required": ["sections", "prosemirror", "plain_text"],
}


def build_submit_tool(handler) -> Tool:
    """The terminal ``submit_proposal`` tool, gated by the driver.

    Terminality is decided per call: the gates run inside ``handler``, and the
    tool only ends the loop when the draft is accepted or the round budget is
    spent -- the runner flips ``is_terminal`` accordingly. While rounds remain,
    a rejected submit returns its gaps with the tool non-terminal so the agent
    revises and submits again.
    """
    return Tool(
        name="submit_proposal",
        description=(
            "Submit the finished proposal for the deterministic gate. Provide "
            "sections (title, hypothesis, approach, why_this_team, "
            "scope_timeline), a ProseMirror `prosemirror` doc, `plain_text`, "
            "and `citations` (each from a tool result). If the gate rejects "
            "the draft it returns concrete gaps -- revise and submit again."
        ),
        input_schema=SUBMIT_INPUT_SCHEMA,
        handler=handler,
        is_terminal=False,
    )


def compose_proposal_toolset(
    *,
    openalex_toolset,
    context_toolset,
    fulltext_toolset,
    web_search_toolset,
    verification_toolset,
    panel,
    judge_context_provider,
    submit_tool: Tool,
) -> Toolset:
    """OpenAlex + context + fulltext + web + verification + judge + submit."""
    toolset = Toolset()
    # OpenAlex tools, minus that toolset's own terminal submit_profile -- the
    # proposal agent has its own terminal tool.
    for tool in openalex_toolset.build_tools():
        if tool.name == SUBMIT_PROFILE:
            continue
        toolset.add(tool)
    for tool in context_toolset.build_tools():
        toolset.add(tool)
    for tool in fulltext_toolset.build_tools():
        toolset.add(tool)
    for tool in web_search_toolset.build_tools():
        toolset.add(tool)
    for tool in verification_toolset.build_tools():
        toolset.add(tool)
    toolset.add(build_judge_tool(panel, context_provider=judge_context_provider))
    toolset.add(submit_tool)
    return toolset
