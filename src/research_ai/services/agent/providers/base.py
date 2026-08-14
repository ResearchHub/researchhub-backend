"""Provider adapter interface.

An ``LLMProvider`` is the only place that knows a vendor's wire format. The
agent loop and toolset speak exclusively in the neutral types from
``agent.types``; each adapter renders those to its provider's request shape and
parses the response back into an ``AssistantTurn``.

Adapters expose exactly two public methods -- ``render_tools`` and ``complete``.
``render_messages`` / ``parse_turn`` are private helpers per adapter.

Id-correlation invariant (every adapter must preserve it): the ``id`` of a
``ToolUseBlock`` the model emits is echoed back as the ``tool_use_id`` of the
``ToolResultBlock`` carrying that call's result. Provider formats key tool
results to tool uses by this id; rendering and parsing must keep them aligned.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import AssistantTurn, Message


class LLMProvider(ABC):
    """Renders neutral agent types to/from a single provider's wire format."""

    @property
    def native_tool_names(self) -> frozenset[str]:
        """Names this provider serves itself, server-side.

        A name listed here needs no local ``Tool``: the provider declares the
        tool on its own and runs it inside the turn, so the toolset must leave
        that name free rather than register a client-side implementation of it
        (two tools sharing a name is a request-validation error). Empty for
        providers whose tools are all client-side.
        """
        return frozenset()

    @abstractmethod
    def render_tools(self, tools: list[Tool]) -> Any:
        """Render ``tools`` to this provider's tool-config wire format."""
        raise NotImplementedError

    @abstractmethod
    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[Message],
        rendered_tools: Any,
        max_tokens: int | None,
        temperature: float,
        before_retry: Callable[[], None] | None = None,
    ) -> AssistantTurn:
        """Run one model turn and return the parsed ``AssistantTurn``.

        ``rendered_tools`` is whatever ``render_tools`` produced for this
        provider; it is passed through opaquely. ``max_tokens=None`` means the
        adapter's own output ceiling for its model. A provider that retries
        internally must invoke ``before_retry`` immediately before spending on
        another request, when supplied.
        """
        raise NotImplementedError
