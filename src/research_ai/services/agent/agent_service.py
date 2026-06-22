"""Factory for building configured ``Agent`` instances.

Resolves the provider from settings (constructor-injectable for tests) and wires
it to a caller-supplied toolset and prompt. Settings (all optional, with
defaults):

- ``RESEARCH_AI_GENERATOR_PROVIDER`` (default ``"bedrock"``)
- ``RESEARCH_AI_GENERATOR_MODEL_ID`` (read by the provider)
- ``RESEARCH_AI_AGENT_MAX_ITERATIONS`` (default ``12``)
"""

from django.conf import settings

from research_ai.services.agent.loop import Agent
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.providers.bedrock import BedrockProvider
from research_ai.services.agent.tools import Toolset

_DEFAULT_PROVIDER = "bedrock"
_DEFAULT_MAX_ITERATIONS = 12


class AgentService:
    """Builds ``Agent``s from a provider name + toolset + prompts."""

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        provider_name: str | None = None,
        max_iterations: int | None = None,
    ):
        # An explicit ``provider`` short-circuits resolution (used in tests).
        self._provider = provider
        self._provider_name = provider_name or getattr(
            settings, "RESEARCH_AI_GENERATOR_PROVIDER", _DEFAULT_PROVIDER
        )
        self._max_iterations = (
            max_iterations
            if max_iterations is not None
            else getattr(
                settings,
                "RESEARCH_AI_AGENT_MAX_ITERATIONS",
                _DEFAULT_MAX_ITERATIONS,
            )
        )

    def _build_provider(self) -> LLMProvider:
        if self._provider is not None:
            return self._provider
        if self._provider_name == "bedrock":
            return BedrockProvider()
        raise ValueError(f"unknown provider: {self._provider_name}")

    def create_agent(
        self,
        toolset: Toolset,
        *,
        system_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        max_iterations: int | None = None,
    ) -> Agent:
        """Build an ``Agent`` for ``toolset`` with the resolved provider."""
        return Agent(
            self._build_provider(),
            toolset,
            system_prompt=system_prompt,
            max_iterations=(
                max_iterations if max_iterations is not None else self._max_iterations
            ),
            max_tokens=max_tokens,
            temperature=temperature,
        )
