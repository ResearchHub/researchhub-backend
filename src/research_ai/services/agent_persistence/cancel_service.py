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

Stopping partway through leaves the record disagreeing with the conversation the
user can see, in both directions, and cancelling reconciles the two. A turn
cancelled before it ran never recorded the prompt that started it, though the
chat shows it; a turn cancelled just after its last answer recorded that answer
but never published it, and never will, because publication requires a
``SUCCEEDED`` execution. Left alone, the next turn -- which continues from this
execution's context -- would answer a conversation missing a message the user
sent, or resume from one they never received.
"""

import logging

from django.db import transaction
from django.utils import timezone

from research_ai.models import AgentContextMessage, AgentExecution
from research_ai.services.agent.types import Message, TextBlock
from research_ai.services.agent_persistence.content import serialize_context_message
from research_ai.services.usage_budget.reservation import reservation_deadline

logger = logging.getLogger(__name__)

CANCELLED_STOP_REASON = "cancelled"


class AgentExecutionCancelService:
    """Cancels executions on request."""

    def cancel(self, execution: AgentExecution) -> bool:
        """Mark an active execution ``CANCELLED``; report whether it landed.

        No error fields are written: a cancellation is the user's own decision,
        not a failure, and the status alone says so. A queued execution releases
        its usage reservation here because no provider call started. A running
        execution keeps a renewable lease until its worker observes the
        cancellation and unwinds. If the worker died, that lease expires instead
        of blocking the user forever. Returns ``False`` when the execution already
        reached a terminal state, which is the ordinary race of cancelling a turn
        that was finishing anyway.
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
            was_pending = locked.status == AgentExecution.Status.PENDING
            locked.status = AgentExecution.Status.CANCELLED
            locked.stop_reason = CANCELLED_STOP_REASON
            locked.finished_at = now
            locked.last_activity_at = now
            # Set this from the claimed state rather than preserving the old
            # value so executions already running during a rolling deployment
            # receive the same protection as newly admitted work.
            locked.usage_reservation_expires_at = (
                None if was_pending else reservation_deadline(now)
            )
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
                    "usage_reservation_expires_at",
                    "updated_date",
                ]
            )
            self._preserve_trigger_prompt(locked)
            self._drop_unpublished_answer(locked)
        execution.refresh_from_db()
        return True

    def _drop_unpublished_answer(self, execution: AgentExecution) -> None:
        """Forget a final answer this turn recorded but never delivered.

        The mirror of :meth:`_preserve_trigger_prompt`. A run cancelled between
        recording its closing assistant turn and transitioning to ``SUCCEEDED``
        keeps that answer in its context but never publishes it -- publication
        requires ``SUCCEEDED``, so not even the repair path will pick it up later.
        The next turn would then continue from a reply the user never saw, and
        answer as though it had already said something it never did.

        Only a *closing* answer goes. An assistant turn holding tool calls is
        load-bearing lineage: a later turn seals its open calls, and dropping it
        would leave tool results with nothing to attach to.

        Nothing here needs to ask whether the answer was published. Publishing
        requires a ``SUCCEEDED`` execution, and a succeeded one is terminal, so
        the caller has already returned before reaching this -- an answer that
        was delivered is one this method never sees.
        """
        if not execution.publish_output_to_chat:
            # No chat to diverge from -- a headless workflow's context is only
            # ever read by the model, so there is no answer "the user missed".
            return
        last = execution.context_messages.order_by("-sequence").first()
        if last is None or last.role != "assistant":
            return
        blocks = last.content if isinstance(last.content, list) else []
        if any(
            isinstance(block, dict) and block.get("type") == "tool_use"
            for block in blocks
        ):
            return
        last.delete()
        logger.info(
            "dropped an unpublished answer from a cancelled turn",
            extra={"execution_id": execution.id},
        )

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
