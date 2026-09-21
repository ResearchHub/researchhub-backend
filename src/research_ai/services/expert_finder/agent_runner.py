"""Expert-finder agent: OpenAlex discovery + Brave contact + SES gate."""

import json
import logging
from typing import Any

from research_ai.constants import (
    EXPERT_FINDER_DEFAULT_STATE,
    ExpertiseLevel,
    Region,
    get_choice_label,
)
from research_ai.prompts._loader import load_template
from research_ai.prompts.expert_finder_prompts import (
    EXPERTISE_DESCRIPTIONS,
    REGION_DESCRIPTIONS,
    build_excluded_experts_instruction,
    format_additional_context_section,
)
from research_ai.services.agent import (
    AgentService,
    LLMProvider,
    Tool,
    Toolset,
    resolve_provider,
)
from research_ai.services.agent.errors import BudgetExceededError
from research_ai.services.expert_finder.display import ExpertDisplay
from research_ai.services.expert_finder.email_validation import (
    EmailValidateToolset,
    EmailValidationService,
)
from research_ai.services.expert_finder.json_parsing import ExpertFinderJson
from research_ai.services.expert_finder.openalex_tools import (
    ExpertFinderOpenAlexToolset,
)
from research_ai.services.expert_finder.region_filter import author_matches_region
from research_ai.services.expert_finder.web_search_tools import (
    ExpertFinderWebSearchToolset,
)
from research_ai.utils import trimmed_str
from utils.brave_search import BraveSearch
from utils.openalex import OpenAlex, normalize_openalex_id

logger = logging.getLogger(__name__)

SUBMIT_EXPERTS = "submit_experts"

_MAX_ITERATIONS = 28  # tool turns before the agent loop gives up

_SYSTEM_PROMPT = load_template("expert_finder_agent_system.txt").strip()

_SUBMIT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "experts": {
            "type": "array",
            "description": (
                "Grounded experts with validated professional emails. "
                "Prefer fewer over inventing fillers."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "openalex_author_id": {
                        "type": "string",
                        "description": (
                            "OpenAlex author id or URL returned by a tool "
                            "this run (required)."
                        ),
                    },
                    "honorific": {"type": "string"},
                    "first_name": {"type": "string"},
                    "middle_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "name_suffix": {"type": "string"},
                    "academic_title": {"type": "string"},
                    "affiliation": {"type": "string"},
                    "expertise": {"type": "string"},
                    "email": {
                        "type": "string",
                        "description": "Professional email (validated).",
                    },
                    "notes": {"type": "string"},
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "url": {"type": "string"},
                            },
                            "required": ["text", "url"],
                        },
                    },
                },
                "required": [
                    "openalex_author_id",
                    "first_name",
                    "last_name",
                    "email",
                ],
            },
        }
    },
    "required": ["experts"],
}


def _normalize_expertise_levels(expertise_level: list[str] | str) -> list[str]:
    if isinstance(expertise_level, str):
        return [expertise_level] if expertise_level else []
    if not expertise_level:
        return []
    flat: list[str] = []
    for item in expertise_level:
        if isinstance(item, str):
            flat.append(item)
        elif isinstance(item, list):
            flat.extend(x for x in item if isinstance(x, str))
    return flat


def _expertise_levels_display(expertise_level: list[str] | str) -> str:
    levels = _normalize_expertise_levels(expertise_level)
    if not levels or (len(levels) == 1 and levels[0] == ExpertiseLevel.ALL_LEVELS):
        return ExpertiseLevel.ALL_LEVELS.label
    return ", ".join(get_choice_label(level, ExpertiseLevel) for level in levels)


def _expertise_instruction(expertise_level: list[str] | str) -> str:
    levels = _normalize_expertise_levels(expertise_level)
    if not levels or (len(levels) == 1 and levels[0] == ExpertiseLevel.ALL_LEVELS):
        return ""
    lines = []
    for level in levels:
        desc = EXPERTISE_DESCRIPTIONS.get(level, level)
        lines.append(f"• {get_choice_label(level, ExpertiseLevel)}: {desc}")
    return (
        "\n\n## Expertise Level Targeting\nFocus specifically on the following "
        "expertise level(s):\n" + "\n".join(lines)
    )


def _region_instruction(region_filter: str, state_filter: str) -> str:
    parts: list[str] = []
    if region_filter != Region.ALL_REGIONS:
        region_label = get_choice_label(region_filter, Region)
        parts.append(
            f"\n\n## Geographic Region Targeting\nFocus specifically on "
            f"{region_label}: "
            f"{REGION_DESCRIPTIONS.get(region_filter, region_filter)}"
        )
    if region_filter == Region.US and state_filter != EXPERT_FINDER_DEFAULT_STATE:
        parts.append(
            f"\n\n## US State-Specific Targeting\n"
            f"Prefer experts affiliated with institutions in {state_filter} "
            f"when possible. Do not invent experts to satisfy the state."
        )
    return "".join(parts)


def build_agent_system_prompt(
    *,
    expert_count: int,
    expertise_level: list[str] | str,
    region_filter: str,
    state_filter: str = EXPERT_FINDER_DEFAULT_STATE,
    excluded_expert_names: list[str] | None = None,
) -> str:
    """System prompt for the expert-finder agent loop."""
    return (
        _SYSTEM_PROMPT + f"\n\nTarget up to {expert_count} experts "
        f"({_expertise_levels_display(expertise_level)}; "
        f"region={get_choice_label(region_filter, Region)})."
        + _expertise_instruction(expertise_level)
        + _region_instruction(region_filter, state_filter)
        + build_excluded_experts_instruction(excluded_expert_names or [])
    )


def build_agent_user_prompt(
    *,
    query: str,
    expert_count: int,
    expertise_level: list[str] | str,
    region_filter: str,
    additional_context: str | None = None,
) -> str:
    """User turn: RFP / research text plus search constraints."""
    region_label = get_choice_label(region_filter, Region)
    region_text = (
        ""
        if region_filter == Region.ALL_REGIONS
        else f" from the {region_label} region"
    )
    payload = {
        "expert_count": expert_count,
        "expertise_level": _expertise_levels_display(expertise_level),
        "region": region_label,
        "region_note": region_text.strip(),
    }
    body = (
        "Find peer experts for this research description. Constraints:\n"
        + json.dumps(payload, indent=2, ensure_ascii=False)
        + "\n\n## Research description\n"
        + (query or "").strip()
        + format_additional_context_section(additional_context)
        + "\n\nCall submit_experts when done."
    )
    return body


def _openalex_author_url(openalex_author_id: str) -> str:
    bare = normalize_openalex_id(openalex_author_id)
    return f"https://openalex.org/{bare}" if bare else ""


def _ensure_openalex_source(sources: list[dict[str, str]], author_url: str) -> list:
    if not author_url:
        return sources
    for item in sources:
        url = str((item or {}).get("url") or "").strip()
        if url.rstrip("/").lower() == author_url.rstrip("/").lower():
            return sources
    return [{"text": "OpenAlex", "url": author_url}, *sources]


def _full_name(row: dict) -> str:
    # Match prior-search exclusions on personal name (no honorific/suffix).
    return ExpertDisplay.build_name(
        first_name=row.get("first_name"),
        middle_name=row.get("middle_name"),
        last_name=row.get("last_name"),
    ).casefold()


def _excluded_name_set(names: list[str] | None) -> set[str]:
    return {
        str(n or "").strip().casefold() for n in (names or []) if str(n or "").strip()
    }


def ground_submitted_experts(
    experts: list | None,
    *,
    openalex_toolset: ExpertFinderOpenAlexToolset,
    email_validation: EmailValidationService,
    expert_count: int,
    excluded_expert_names: list[str] | None = None,
    region_filter: str = Region.ALL_REGIONS,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop ungrounded / invalid / excluded / out-of-region rows; normalize persist shape.

    Server never trusts model-side ``email_validate`` alone. Region is a hard
    gate on OpenAlex institution country codes.
    """
    errors: list[str] = []
    grounded_rows: list[dict] = []
    excluded = _excluded_name_set(excluded_expert_names)
    region = region_filter or Region.ALL_REGIONS

    if not isinstance(experts, list):
        if experts is not None:
            errors.append(
                f"submitted experts was {type(experts).__name__}, not a list; dropped"
            )
        return [], errors

    for index, row in enumerate(experts):
        if not isinstance(row, dict):
            errors.append(f"experts[{index}]: not an object")
            continue
        author_id = str(row.get("openalex_author_id") or "").strip()
        if not author_id:
            errors.append(f"experts[{index}]: missing openalex_author_id")
            continue
        if not openalex_toolset.has_returned_author(author_id):
            errors.append(
                f"experts[{index}]: dropped ungrounded openalex_author_id {author_id!r}"
            )
            continue
        if excluded and _full_name(row) in excluded:
            errors.append(f"experts[{index}]: excluded by prior-search name")
            continue
        if region != Region.ALL_REGIONS:
            record = openalex_toolset.resolve_author_record(author_id)
            if not author_matches_region(record, region):
                errors.append(
                    f"experts[{index}]: dropped outside region filter {region!r}"
                )
                continue
        grounded_rows.append(row)

    email_kept, email_drops = email_validation.gate_submitted_experts(grounded_rows)
    errors.extend(email_drops)

    kept: list[dict[str, Any]] = []
    limit = max(0, int(expert_count))
    for row in email_kept:
        if limit and len(kept) >= limit:
            break
        author_id = str(row.get("openalex_author_id") or "").strip()
        author_url = _openalex_author_url(author_id)
        sources = _ensure_openalex_source(
            ExpertFinderJson.normalize_sources(row.get("sources")),
            author_url,
        )
        bare = normalize_openalex_id(author_id)
        kept.append(
            {
                "email": row["email"],
                "honorific": trimmed_str(row.get("honorific"), max_len=64),
                "first_name": trimmed_str(row.get("first_name"), max_len=255),
                "middle_name": trimmed_str(row.get("middle_name"), max_len=255),
                "last_name": trimmed_str(row.get("last_name"), max_len=255),
                "name_suffix": trimmed_str(row.get("name_suffix"), max_len=64),
                "academic_title": trimmed_str(row.get("academic_title"), max_len=255),
                "affiliation": trimmed_str(row.get("affiliation")),
                "expertise": trimmed_str(row.get("expertise")),
                "notes": trimmed_str(row.get("notes")),
                "sources": sources,
                "openalex_author_id": author_url or bare or author_id,
                "profile": {
                    "resolution": {
                        "openalex_author_id": author_url or bare or author_id,
                    }
                },
            }
        )
    return kept, errors


class ExpertFinderAgentToolset:
    """Composes OpenAlex + Brave web_search + email_validate + submit_experts."""

    def __init__(
        self,
        *,
        openalex_toolset: ExpertFinderOpenAlexToolset | None = None,
        web_search_toolset: ExpertFinderWebSearchToolset | None = None,
        email_validate_toolset: EmailValidateToolset | None = None,
        oa_client: OpenAlex | None = None,
        web_search_client: BraveSearch | None = None,
        email_validation: EmailValidationService | None = None,
        region_filter: str = Region.ALL_REGIONS,
        state_filter: str = EXPERT_FINDER_DEFAULT_STATE,
    ):
        self.openalex = openalex_toolset or ExpertFinderOpenAlexToolset(
            client=oa_client,
            region_filter=region_filter,
            state_filter=state_filter,
        )
        self.web_search = web_search_toolset or ExpertFinderWebSearchToolset(
            client=web_search_client
        )
        self.email_validate = email_validate_toolset or EmailValidateToolset(
            service=email_validation
        )
        self.submitted: dict | None = None

    def build_tools(self) -> list[Tool]:
        tools: list[Tool] = []
        tools.extend(self.openalex.build_tools())
        tools.extend(self.web_search.build_tools())
        tools.extend(self.email_validate.build_tools())
        tools.append(self._build_submit_tool())
        return tools

    def as_toolset(self, *, native_tool_names: frozenset[str] = frozenset()) -> Toolset:
        """Compose tools, skipping names the provider serves server-side."""
        toolset = Toolset()
        for tool in self.build_tools():
            if tool.name in native_tool_names:
                logger.info(
                    "provider serves %s server-side; local tool skipped", tool.name
                )
                continue
            toolset.add(tool)
        return toolset

    def _build_submit_tool(self) -> Tool:
        return Tool(
            name=SUBMIT_EXPERTS,
            description=(
                "Submit the final list of grounded experts with validated "
                "professional emails. Each expert must include an "
                "openalex_author_id returned by a tool this run. Call exactly "
                "once when finished; prefer fewer experts over inventing fillers."
            ),
            input_schema=_SUBMIT_INPUT_SCHEMA,
            handler=self._submit_experts,
            is_terminal=True,
        )

    def _submit_experts(self, args: dict) -> dict:
        payload = args if isinstance(args, dict) else {}
        experts = payload.get("experts")
        if not isinstance(experts, list):
            return {"error": "experts must be an array"}
        self.submitted = {"experts": experts}
        return {
            "accepted": True,
            "submitted_count": len(experts),
            "message": (
                "Submission received. The server will ground OpenAlex ids and "
                "re-validate emails before persist."
            ),
        }


def run_expert_finder_agent(
    *,
    query: str,
    expert_count: int,
    expertise_level: list[str] | str,
    region_filter: str,
    state_filter: str = EXPERT_FINDER_DEFAULT_STATE,
    excluded_expert_names: list[str] | None = None,
    additional_context: str | None = None,
    provider: LLMProvider | None = None,
    oa_client: OpenAlex | None = None,
    web_search_client: BraveSearch | None = None,
    email_validation: EmailValidationService | None = None,
    recorder=None,
    max_iterations: int = _MAX_ITERATIONS,
) -> dict[str, Any]:
    """Run the expert-finder agent and return grounded expert rows.

    Returns ``{"experts": [...], "errors": [...]}``. Budget exhaustion
    propagates so the owning Celery task can stop cleanly; other agent failures
    are recorded in ``errors`` and yield an empty expert list.
    """
    errors: list[str] = []
    email_service = email_validation or EmailValidationService()
    toolset = ExpertFinderAgentToolset(
        oa_client=oa_client,
        web_search_client=web_search_client,
        email_validation=email_service,
        region_filter=region_filter,
        state_filter=state_filter,
    )
    provider = provider or resolve_provider()
    agent = AgentService(provider=provider, max_iterations=max_iterations).create_agent(
        toolset.as_toolset(native_tool_names=provider.native_tool_names),
        system_prompt=build_agent_system_prompt(
            expert_count=expert_count,
            expertise_level=expertise_level,
            region_filter=region_filter,
            state_filter=state_filter,
            excluded_expert_names=excluded_expert_names,
        ),
        recorder=recorder,
    )

    try:
        agent.run(
            build_agent_user_prompt(
                query=query,
                expert_count=expert_count,
                expertise_level=expertise_level,
                region_filter=region_filter,
                additional_context=additional_context,
            )
        )
    except BudgetExceededError:
        raise
    except Exception as exc:  # noqa: BLE001 - agent run is best-effort
        logger.exception("expert-finder agent failed")
        errors.append(f"agent: {exc}")

    if toolset.submitted is None:
        errors.append("agent: did not submit experts")
        return {"experts": [], "errors": errors}

    kept, gate_errors = ground_submitted_experts(
        toolset.submitted.get("experts"),
        openalex_toolset=toolset.openalex,
        email_validation=email_service,
        expert_count=expert_count,
        excluded_expert_names=excluded_expert_names,
        region_filter=region_filter,
    )
    errors.extend(gate_errors)
    return {"experts": kept, "errors": errors}
