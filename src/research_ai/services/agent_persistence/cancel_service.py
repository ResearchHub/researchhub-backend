"""Cooperative cancellation for agent executions.

A conversation permits one active execution, so one that never reaches a
terminal status refuses every later turn as busy -- what happens when a worker
dies before recording an outcome, or the broker never delivers a queued attempt.
Cancelling unsticks it, and is deliberately the only way: no timeout is guessed
at here, because one provider call can retry inside the vendor SDK for over an
hour, so silence says nothing about whether a run is alive.

It does not reach into the worker. The run stops before its next tool call,
where the loop checks it still owns the execution, or at its next durable write,
which refuses to extend a terminal execution. A ``PENDING`` execution needs
neither: its claim is a conditional update, so a task delivered afterwards finds
nothing left to claim.
"""

import logging

from django.db import transaction
from django.utils import timezone

from research_ai.models import AgentContextMessage, AgentExecution
from research_ai.services.agent.types import Message, TextBlock
from research_ai.services.agent_persistence.content import serialize_context_message

logger = logging.getLogger(__name__)

CANCELLED_STOP_REASON = "cancelled"


class AgentExecutionCancelService:
    """Cancels executions on request."""

    def cancel(self, execution: AgentExecution) -> bool:
        """Mark an active execution ``CANCELLED``; report whether it landed.

        No error fields are written: a cancellation is the user's own decision,
        not a failure, and the status alone says so. Returns ``False`` when the
        execution already reached a terminal state, which is the ordinary race
        of cancelling a turn that was finishing anyway.
        """
        with transaction.atomic():
            locked = (
                AgentExecution.objects.select_for_update()
                .filter(
                    id=execution.id,
                    status__in=[
                        AgentExecution.Status.PENDING,
                        AgentExecution.Status.RUNNING,
                    ],
                )
                .first()
            )
            if locked is None:
                return False
            now = timezone.now()
            locked.status = AgentExecution.Status.CANCELLED
            locked.stop_reason = CANCELLED_STOP_REASON
            locked.finished_at = now
            locked.last_activity_at = now
            if locked.started_at is not None:
                locked.duration_ms = max(
                    0, round((now - locked.started_at).total_seconds() * 1000)
                )
            locked.save(
                update_fields=[
                    "status",
                    "stop_reason",
                    "finished_at",
                    "last_activity_at",
                    "duration_ms",
                    "updated_date",
                ]
            )
            self._preserve_trigger_prompt(locked)
        execution.refresh_from_db()
        return True

    def _preserve_trigger_prompt(self, execution: AgentExecution) -> None:
        """Seed the context with the prompt this turn never got to record.

        A cancelled execution is a continuation parent, and reconstruction reads
        context rows only -- so whatever is missing here the model never sees
        again. A ``RUNNING`` turn already recorded its seed prompt, but one
        cancelled while still ``PENDING`` never ran, and its prompt lives only in
        the chat message that triggered it. Left alone, the next turn would
        inherit a conversation with a user message visible on screen and absent
        from the model's view of it.
        """
        if execution.context_messages.exists():
            return
        trigger = execution.trigger_message
        if trigger is None or not (trigger.content or "").strip():
            return
        content, provider_state, is_compacted, original_size = (
            serialize_context_message(
                Message(role="user", content=[TextBlock(text=trigger.content)])
            )
        )
        AgentContextMessage.objects.create(
            execution=execution,
            sequence=execution.next_context_sequence,
            role="user",
            content=content,
            provider_state=provider_state,
            is_compacted=is_compacted,
            original_size_bytes=original_size if is_compacted else None,
        )
        execution.next_context_sequence += 1
        execution.save(update_fields=["next_context_sequence", "updated_date"])
