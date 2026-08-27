"""Liveness sweep for agent executions whose worker silently died.

A conversation permits one active execution, so a ``RUNNING`` row whose worker
was OOM-killed, redeployed, or SIGKILLed -- and a ``PENDING`` row whose task
was never delivered or claimed -- blocks every later turn on the conversation
forever. The sweep finds those rows by their durable heartbeat
(``last_activity_at``, stamped on every recorder write) and seals them
``INTERRUPTED`` through the cancel service, which reconciles the recorded
context with what the chat shows.

Staleness thresholds must not undercut the turn task's own time limits: a live
worker can go heartbeat-quiet for a whole model turn, and the task's soft time
limit is what bounds that. Reaping earlier than the limit would interrupt
healthy long turns; see ``run_notebook_chat_turn_task`` in
``research_ai.tasks``.

The sweep covers every workflow sharing the execution models (notebook chat,
proposal drafting); callers that push user-facing events layer that on per
reaped execution.
"""

import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from research_ai.models import AgentExecution
from research_ai.services.agent_persistence.cancel_service import (
    AgentExecutionCancelService,
)

logger = logging.getLogger(__name__)

# Kept at (not under) the turn task's soft time limit plus scheduling slack, so
# only a run whose worker is really gone can look stale.
RUNNING_STALE_AFTER = timedelta(minutes=15)

# A queued turn is normally claimed within seconds; this covers the stranded
# window where the broker accepted the task but no worker ever ran it.
PENDING_STALE_AFTER = timedelta(minutes=15)

STALLED_STOP_REASON = "stalled"
STALLED_ERROR_TYPE = "AgentExecutionStalled"


class AgentExecutionReaperService:
    """Seals executions abandoned by a dead worker or a lost task."""

    def __init__(
        self,
        *,
        cancel_service: AgentExecutionCancelService | None = None,
        running_stale_after: timedelta = RUNNING_STALE_AFTER,
        pending_stale_after: timedelta = PENDING_STALE_AFTER,
    ):
        self.cancels = (
            AgentExecutionCancelService() if cancel_service is None else cancel_service
        )
        self.running_stale_after = running_stale_after
        self.pending_stale_after = pending_stale_after

    def reap(self, *, now: datetime | None = None) -> list[AgentExecution]:
        """Interrupt every stale active execution; return the rows sealed here."""
        now = timezone.now() if now is None else now
        reaped = []
        for execution_id in self._stale_execution_ids(now):
            execution = self._reap_one(execution_id, now)
            if execution is not None:
                reaped.append(execution)
        return reaped

    def _stale_q(self, now: datetime) -> Q:
        running_cutoff = now - self.running_stale_after
        pending_cutoff = now - self.pending_stale_after
        # Every RUNNING row gets a heartbeat at claim time; the fallback on
        # ``updated_date`` only keeps a row with a manually blanked heartbeat
        # from becoming unreapable.
        running_stale = Q(status=AgentExecution.Status.RUNNING) & (
            Q(last_activity_at__lt=running_cutoff)
            | (Q(last_activity_at__isnull=True) & Q(updated_date__lt=running_cutoff))
        )
        pending_stale = Q(
            status=AgentExecution.Status.PENDING, created_date__lt=pending_cutoff
        )
        return running_stale | pending_stale

    def _stale_execution_ids(self, now: datetime) -> list[int]:
        return list(
            AgentExecution.objects.filter(self._stale_q(now))
            .order_by("id")
            .values_list("id", flat=True)
        )

    def _reap_one(self, execution_id: int, now: datetime) -> AgentExecution | None:
        """Seal one candidate, re-checking staleness under the row lock.

        The heartbeat can advance between the sweep's scan and this write; the
        locked re-read is what makes interrupting a live run impossible rather
        than merely unlikely. ``skip_locked`` treats a row a worker is writing
        this instant as alive, and keeps concurrent sweeps off each other.
        """
        with transaction.atomic():
            execution = (
                AgentExecution.objects.select_for_update(skip_locked=True)
                .filter(self._stale_q(now), id=execution_id)
                .first()
            )
            if execution is None:
                return None
            was_pending = execution.status == AgentExecution.Status.PENDING
            if was_pending:
                minutes = round(self.pending_stale_after.total_seconds() / 60)
                error_message = (
                    f"The queued turn was not claimed by any worker within "
                    f"{minutes} minutes."
                )
            else:
                minutes = round(self.running_stale_after.total_seconds() / 60)
                error_message = (
                    f"The turn recorded no activity for over {minutes} minutes; "
                    f"its worker likely died."
                )
            if not self.cancels.interrupt(
                execution,
                stop_reason=STALLED_STOP_REASON,
                error_type=STALLED_ERROR_TYPE,
                error_message=error_message,
                error_details={"stop_reason": STALLED_STOP_REASON},
            ):
                return None
        logger.warning(
            "reaped a stale agent execution",
            extra={
                "execution_id": execution.id,
                "conversation_id": execution.conversation_id,
                "was_pending": was_pending,
            },
        )
        return execution
