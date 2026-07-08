"""Recorder protocol for observing agent runs without coupling to Django."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from research_ai.services.agent.types import AssistantTurn, Message

if TYPE_CHECKING:
    from research_ai.services.agent.errors import AgentRunError
    from research_ai.services.agent.loop import AgentResult


class AgentRecorder(Protocol):
    """Observes appended messages and run terminal states."""

    def record_message(
        self, message: Message, *, turn: AssistantTurn | None = None
    ) -> None:
        """Record a newly appended message.

        ``turn`` is supplied only for assistant messages so usage, latency, and
        stop reason can be persisted without storing provider-specific raw data.
        """

    def on_run_finished(self, result: AgentResult) -> None:
        """Record successful run completion."""

    def on_run_failed(self, error: AgentRunError) -> None:
        """Record failed run completion."""
