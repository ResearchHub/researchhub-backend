"""Factory for building configured ``Agent`` instances.

Wires a provider to a caller-supplied toolset and prompt. The constructor takes
no defaults: callers pass each value explicitly (resolving from settings such as
``RESEARCH_AI_GENERATOR_PROVIDER`` / ``RESEARCH_AI_AGENT_MAX_ITERATIONS`` at the
call site). Pass an explicit ``provider`` to inject one (used in tests), or
``provider=None`` to resolve it from ``provider_name``.
"""

from research_ai.services.agent.loop import Agent
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.providers.bedrock import BedrockProvider
from research_ai.services.agent.tools import Toolset


class AgentService:
    """Builds ``Agent``s from a provider name + toolset + prompts."""

    def __init__(
        self,
        *,
        provider: LLMProvider | None,
        provider_name: str,
        max_iterations: int,
    ):
        # An explicit ``provider`` short-circuits resolution (used in tests);
        # otherwise the provider is built from ``provider_name``.
        self._provider = provider
        self._provider_name = provider_name
        self._max_iterations = max_iterations

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
