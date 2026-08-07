"""Cooperative cancellation for agent executions.

A linear conversation permits only one active execution
(``ra_agent_exec_one_active``), so an execution that never reaches a terminal
status refuses every later turn on its conversation as busy. That happens for
real: a worker can die between claiming an execution and recording its outcome
-- a deploy, an OOM kill, a lost broker connection -- and a queued attempt the
broker never delivered strands a conversation the same way while sitting
``PENDING``. Cancellation is how both get unstuck, and it is deliberately the
*only* way: the remedy is a decision someone makes, not a timeout this code
guesses at.

That choice is what keeps this module small. Nothing here reads how long a run
has been quiet, so nothing has to know how long quiet is normal -- a question
with no good answer, since a single provider call may retry inside the vendor
SDK for well over an hour and a tool handler may make several of those before it
returns. Every workflow that starts an execution exposes a cancel endpoint
instead, and both surface the stuck row exactly where it blocks someone: a busy
conversation answers 409, and a blocked proposal draft answers 409 naming the
draft to cancel.

Cancellation itself is cooperative. Marking a ``RUNNING`` execution
``CANCELLED`` does not reach into the worker. The worker stops at one of two
points: before its next *tool call*, where the loop checks that it still owns
the execution (:meth:`DatabaseAgentRecorder.is_active`) so a cancelled turn
cannot still edit a note; or failing that, at its next durable write, where the
recorder refuses to append to a terminal execution and raises
``InterruptedError`` and the run unwinds through its ordinary failure path. A
``PENDING`` execution cancels even more simply: the claim is a conditional
update on ``PENDING``, so a task delivered afterwards finds nothing to claim.
"""

import logging

from django.db import transaction
from django.utils import timezone

from research_ai.models import AgentExecution

logger = logging.getLogger(__name__)

CANCELLED_STOP_REASON = "cancelled"


class AgentLivenessService:
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
        execution.refresh_from_db()
        return True
