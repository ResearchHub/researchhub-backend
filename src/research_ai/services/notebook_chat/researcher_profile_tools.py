"""Researcher-profile read tool for the notebook chat agent.

Exposes the acting user's ``ResearcherProfile`` -- the grounded researcher
profile the profile agent builds -- to the chat agent. Scoped to the
conversation's user: no selector is accepted from the model, mirroring
``UserProfileToolset``'s identity boundary. A missing or stale profile is
queued for a background build; the agent is told when one is on its way.
"""

import logging

from research_ai.models import ResearcherProfile
from research_ai.services.agent import Tool, Toolset
from research_ai.services.researcher_profile import (
    ResearcherProfileService,
    schedule_profile_build,
)
from user.models import User

logger = logging.getLogger(__name__)

GET_RESEARCHER_PROFILE = "get_researcher_profile"

_EMPTY_INPUT_SCHEMA = {"type": "object", "properties": {}}
_PROFILE_KEYS = ("schema_version", "built_at", "resolution", "works", "capabilities")


class ResearcherProfileToolset:
    """Read the acting user's expert researcher profile."""

    def __init__(self, *, user: User, service: ResearcherProfileService | None = None):
        self._user = user
        self._service = service or ResearcherProfileService()

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
                    "It may be absent, still being built, partial, or "
                    "unresolved; work from get_user_profile and the OpenAlex "
                    "tools then."
                ),
                input_schema=_EMPTY_INPUT_SCHEMA,
                handler=self._get_researcher_profile,
            )
        ]

    def as_toolset(self) -> Toolset:
        return Toolset(self.build_tools())

    def _get_researcher_profile(self, _args: dict) -> dict:
        try:
            profile = self._service.profile_for_user(self._user)
            queued = profile is None or self._service.needs_build(profile)
        except Exception:  # noqa: BLE001 - tool failures are model-readable
            logger.exception("researcher profile read failed")
            return {"error": "researcher profile is temporarily unavailable"}
        if queued:
            schedule_profile_build(self._user)
        if profile is not None and profile.has_data:
            data = {key: profile.data.get(key) for key in _PROFILE_KEYS}
            if profile.status == ResearcherProfile.Status.FAILED:
                # The latest rebuild failed, possibly after the user changed
                # their identity, so the kept profile may describe them wrongly.
                return {
                    "status": "stale",
                    "profile": data,
                    "guidance": (
                        "This profile could not be refreshed and may be out of "
                        "date or describe a different person. Confirm the "
                        "identity against get_user_profile before relying on "
                        "it, and never invent a track record."
                    ),
                }
            return {"status": "ready", "profile": data}
        if queued or (
            profile is not None and profile.status == ResearcherProfile.Status.BUILDING
        ):
            return {
                "status": "building",
                "guidance": (
                    "ResearchHub is building this user's expert profile in the "
                    "background; it is not available yet. Work from "
                    "get_user_profile and the OpenAlex tools instead, and never "
                    "invent a track record."
                ),
            }
        return {
            "status": "no_profile",
            "guidance": (
                "ResearchHub has no expert profile for this user. Work "
                "from get_user_profile and the OpenAlex tools instead, "
                "and never invent a track record."
            ),
        }
