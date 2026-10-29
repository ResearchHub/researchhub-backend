"""Tool composition for the proposal-drafting agent.

Builds the terminal ``submit_proposal`` tool and assembles the full toolset
the agent runs with (OpenAlex + context + fulltext + web + verification +
submit). The submit handler stays with the runner -- it closes over run state;
this module owns only the static schema and the wiring.
"""

import logging

from research_ai.services.agent import Tool, Toolset
from research_ai.services.researcher_profile.openalex_tools import (
    GET_WORK_FULLTEXT,
    SUBMIT_PROFILE,
)

logger = logging.getLogger(__name__)

SUBMIT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "background": {"type": "string"},
                "preliminary_data": {"type": "string"},
                "aims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "body": {"type": "string"},
                        },
                        "required": ["title", "body"],
                    },
                },
                "limitations": {"type": "string"},
                "why_this_team": {"type": "string"},
                "budget": {"type": "string"},
                "timeline": {"type": "string"},
            },
            "required": [
                "title",
                "background",
                "preliminary_data",
                "aims",
                "limitations",
                "why_this_team",
                "budget",
                "timeline",
            ],
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
                    "year": {"type": "integer"},
                },
                "required": ["claim_id"],
            },
        },
    },
    "required": ["sections"],
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
            "`sections` (title, background, preliminary_data, aims as a list of "
            "{title, body}, limitations, why_this_team, budget, timeline) and "
            "`citations` "
            "(each from a tool result); the server assembles the final numbered "
            "document from your sections. If the gate rejects the draft it "
            "returns concrete gaps -- revise and submit again."
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
    submit_tool: Tool,
    native_tool_names: frozenset[str] = frozenset(),
) -> Toolset:
    """OpenAlex + context + fulltext + web + verification + submit.

    ``native_tool_names`` are the names the provider runs server-side (on Claude
    Platform, ``web_search``). A local tool by that name is left out: the
    provider declares its own, and sending both would put two tools with one
    name in the request. The agent sees one ``web_search`` either way -- only
    who executes it changes -- so the prompt and the run's shape do not.
    """
    # OpenAlex tools, minus the two this agent replaces: submit_profile (the
    # proposal agent has its own terminal tool) and the profile builder's
    # get_work_fulltext (the fulltext toolset ships the proposal agent's
    # version -- profile-scoped and fetch-capped -- under the same name, which
    # would otherwise replace this one silently via ``Toolset.add``).
    candidates = [
        tool
        for tool in openalex_toolset.build_tools()
        if tool.name not in (SUBMIT_PROFILE, GET_WORK_FULLTEXT)
    ]
    for source in (
        context_toolset,
        fulltext_toolset,
        web_search_toolset,
        verification_toolset,
    ):
        candidates.extend(source.build_tools())
    candidates.append(submit_tool)

    toolset = Toolset()
    for tool in candidates:
        if tool.name in native_tool_names:
            logger.info("provider serves %s server-side; local tool skipped", tool.name)
            continue
        toolset.add(tool)
    return toolset
