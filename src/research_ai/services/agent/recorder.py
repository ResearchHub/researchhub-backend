"""Transcript recording hook for the agent loop.

An ``AgentRecorder`` observes a run as it happens: the loop calls
``record_message`` at each point a ``Message`` is appended to the conversation
(the seed user turn, each assistant turn, each tool-result turn), then exactly
one of ``on_run_finished`` / ``on_run_failed`` when the run ends.

This module defines only the protocol -- implementations live outside the
``agent`` package and are injected by callers, keeping the core Django-free.
Message-hook failures are best-effort unless an implementation opts into the
``requires_durable_messages`` contract; terminal-hook failures are logged
without masking the original run outcome.
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
        metadata (usage, latency, stop reason) alongside the content. A recorder
        that sets ``requires_durable_messages`` may propagate required-write
        failures; optional writes should be isolated by the implementation.
        """
        ...

    def on_run_finished(self, result: AgentResult) -> bool | None:
        """The run completed; every message was already recorded.

        A recorder that persists a terminal outcome reports whether this call
        performed the transition itself: ``False`` means the run was already
        sealed from elsewhere (cancelled, for instance) and the result was
        discarded. Observers layered over such a recorder use the report to
        stay silent about outcomes that never landed; the loop ignores it,
        and recorders that do not track it return ``None``.
        """
        ...

    def on_run_failed(self, error: Exception) -> bool | None:
        """The run failed; every message up to the failure was recorded.

        Reports whether this call sealed the run, under the same contract as
        ``on_run_finished``.
        """
        ...

    def is_active(self) -> bool:
        """Whether this run still owns the work it is recording.

        Optional. Recorders whose run can be cancelled from outside implement
        this so the loop can stop *before* a tool call takes effect rather than
        discovering it at the next write, which happens only after the side
        effect. A recorder without it is treated as always active, so nothing is
        required of observers that cannot be pre-empted.
        """
        ...
