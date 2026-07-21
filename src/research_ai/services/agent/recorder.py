"""Transcript recording hook for the agent loop.

An ``AgentRecorder`` observes a run as it happens: the loop calls
``record_message`` at each point a ``Message`` is appended to the conversation
(the seed user turn, each assistant turn, each tool-result turn), then exactly
one of ``on_run_finished`` / ``on_run_failed`` when the run ends.

This module defines only the protocol -- implementations live outside the
``agent`` package (e.g. a Django recorder persisting transcript entries) and
are injected by callers, keeping the core Django-free. The loop wraps every
recorder call: a raising recorder is logged and ignored, never fatal to the
run (a transcript is observability, same contract as ``progress_callback``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from research_ai.services.agent.types import AssistantTurn, Message

if TYPE_CHECKING:
    from research_ai.services.agent.loop import AgentResult


class AgentRecorder(Protocol):
    """Observes messages and the terminal outcome of one agent run."""

    def record_message(
        self, message: Message, *, turn: AssistantTurn | None = None
    ) -> None:
        """Record one appended message.

        ``turn`` is set only for assistant messages, carrying the per-turn
        metadata (usage, latency, stop reason) alongside the content.
        """
        ...

    def on_run_finished(self, result: AgentResult) -> None:
        """The run completed; every message was already recorded."""
        ...

    def on_run_failed(self, error: Exception) -> None:
        """The run failed; every message up to the failure was recorded."""
        ...
