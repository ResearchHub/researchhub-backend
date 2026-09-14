"""Researcher-profile read tool for the notebook chat agent.

Exposes the acting user's ``Expert.profile`` -- the grounded researcher
profile the expert pipeline builds -- to the chat agent. Read-only and
scoped to the conversation's user: no selector is accepted from the model,
mirroring ``UserProfileToolset``'s identity boundary.
"""

import logging

from research_ai.services.agent import Tool, Toolset
from research_ai.services.researcher_profile.user_expert import expert_for_user
from user.models import User

logger = logging.getLogger(__name__)

GET_RESEARCHER_PROFILE = "get_researcher_profile"

_EMPTY_INPUT_SCHEMA = {"type": "object", "properties": {}}
_PROFILE_KEYS = ("schema_version", "built_at", "resolution", "works", "capabilities")


class ResearcherProfileToolset:
    """Read the acting user's expert researcher profile."""

    def __init__(self, *, user: User):
        self._user = user

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name=GET_RESEARCHER_PROFILE,
                description=(
                    "Read the expert researcher profile ResearchHub holds for "
                    "the current user, when one exists: their resolved "
                    "OpenAlex identity, key works, and demonstrated lab "
                    "capabilities backed by their papers. Use it to ground "
                    "drafting in what the user's record actually supports. "
                    "It may be absent, partial, or unresolved; work from "
                    "get_user_profile and the OpenAlex tools then."
                ),
                input_schema=_EMPTY_INPUT_SCHEMA,
                handler=self._get_researcher_profile,
            )
        ]

    def as_toolset(self) -> Toolset:
        return Toolset(self.build_tools())

    def _get_researcher_profile(self, _args: dict) -> dict:
        try:
            expert = expert_for_user(self._user)
        except Exception:  # noqa: BLE001 - tool failures are model-readable
            logger.exception("researcher profile read failed")
            return {"error": "researcher profile is temporarily unavailable"}
        profile = expert.profile if expert is not None else None
        if not isinstance(profile, dict) or not profile:
            return {
                "status": "no_profile",
                "guidance": (
                    "ResearchHub has no expert profile for this user. Work "
                    "from get_user_profile and the OpenAlex tools instead, "
                    "and never invent a track record."
                ),
            }
        return {
            "status": "ready",
            "profile": {key: profile.get(key) for key in _PROFILE_KEYS},
        }
