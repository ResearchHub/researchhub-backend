"""Factory for building configured ``Agent`` instances.

Wires an injected provider to a caller-supplied toolset and prompt. The
constructor takes no defaults: callers pass each value explicitly (resolving
``max_iterations`` from settings such as ``RESEARCH_AI_AGENT_MAX_ITERATIONS`` at
the call site, and constructing the provider they want -- e.g.
``BedrockProvider()``). A name->provider resolver belongs here only once a
second provider exists and there is a real choice to make.
"""

from research_ai.services.agent.loop import Agent
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.tools import Toolset


class AgentService:
    """Builds ``Agent``s from a provider + toolset + prompts."""

    def __init__(self, *, provider: LLMProvider, max_iterations: int):
        self._provider = provider
        self._max_iterations = max_iterations

    def create_agent(
        self,
        toolset: Toolset,
        *,
        system_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        max_iterations: int | None = None,
    ) -> Agent:
        """Build an ``Agent`` for ``toolset`` with the injected provider."""
        return Agent(
            self._provider,
            toolset,
            system_prompt=system_prompt,
            max_iterations=(
                max_iterations if max_iterations is not None else self._max_iterations
            ),
            max_tokens=max_tokens,
            temperature=temperature,
        )
