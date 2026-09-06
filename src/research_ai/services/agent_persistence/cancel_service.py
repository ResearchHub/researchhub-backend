"""Cooperative cancellation for agent executions.

A conversation permits one active execution, so one that never reaches a
terminal status refuses every later turn as busy -- what happens when a worker
dies before recording an outcome, or the broker never delivers a queued attempt.
Cancelling unsticks it at once; ``AgentExecutionLivenessService`` reclaims it
anyway once the worker's liveness lease lapses. Neither guesses at a timeout on
loop progress: one provider call can retry inside the vendor SDK for over an
hour, so only the worker's heartbeat says whether a run is alive.

It does not reach into the worker. The run stops before its next tool call,
where the loop checks it still owns the execution, or at its next durable write,
which refuses to extend a terminal execution. A ``PENDING`` execution needs
neither: its claim is a conditional update, so a task delivered afterwards finds
nothing left to claim.

Stopping partway through leaves the record disagreeing with the conversation the
user can see; ``reconciliation`` repairs that in both directions.
"""

import logging

from django.db import transaction
from django.utils import timezone

from research_ai.models import AgentExecution
from research_ai.services.agent_persistence.reconciliation import (
    reconcile_stopped_run,
)

logger = logging.getLogger(__name__)

CANCELLED_STOP_REASON = "cancelled"


class AgentExecutionCancelService:
    """Cancels executions on request."""

    def cancel(self, execution: AgentExecution) -> bool:
        """Mark an active execution ``CANCELLED``; report whether it landed.

        No error fields are written: a cancellation is the user's own decision,
        not a failure. A queued execution releases its usage reservation here
        because no provider call started. A running execution keeps its
        liveness lease: the worker renews it while its in-flight provider call
        may still be spending and clears it when it unwinds, and a dead
        worker's lease lapses on its own. Returns ``False`` when the execution
        already reached a terminal state, which is the ordinary race of
        cancelling a turn that was finishing anyway.
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
            update_fields = [
                "status",
                "stop_reason",
                "finished_at",
                "last_activity_at",
                "duration_ms",
                "updated_date",
            ]
            if was_pending:
                locked.usage_reservation_expires_at = None
                update_fields.append("usage_reservation_expires_at")
            if locked.started_at is not None:
                locked.duration_ms = max(
                    0, round((now - locked.started_at).total_seconds() * 1000)
                )
            locked.save(update_fields=update_fields)
            reconcile_stopped_run(locked)
        execution.refresh_from_db()
        return True
