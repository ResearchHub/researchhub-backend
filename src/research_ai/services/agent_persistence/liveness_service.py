"""Reclaiming executions whose worker stopped heartbeating."""

import logging

from django.db import transaction
from django.utils import timezone

from research_ai.models import AgentExecution
from research_ai.services.agent_persistence.execution_service import (
    AgentExecutionService,
)
from research_ai.services.agent_persistence.reconciliation import (
    reconcile_stopped_run,
)
from research_ai.services.agent_persistence.recorder import DatabaseAgentRecorder

logger = logging.getLogger(__name__)

WORKER_LOST_STOP_REASON = "worker_lost"

_ACTIVE_STATUSES = (AgentExecution.Status.PENDING, AgentExecution.Status.RUNNING)


class WorkerLostError(RuntimeError):
    """Sealed onto an execution whose worker's liveness lease lapsed."""

    stop_reason = WORKER_LOST_STOP_REASON

    def __init__(self, message: str = "the worker stopped heartbeating mid-run"):
        super().__init__(message)


class AgentExecutionLivenessService:
    """Seals active executions whose worker is gone, so they stop blocking.

    A lapsed lease is the only evidence used: a live worker renews its lease
    from a heartbeat thread regardless of loop progress, so silence longer
    than one lease means the process is dead or cut off from the database.
    """

    def __init__(self, *, recorder_factory=None):
        self.recorder_factory = (
            DatabaseAgentRecorder if recorder_factory is None else recorder_factory
        )
        self.executions = AgentExecutionService(recorder_factory=self.recorder_factory)

    def reclaim_lost(self, *, user=None, now=None) -> list[AgentExecution]:
        """Fail every active execution whose lease lapsed, optionally one user's."""
        current = now or timezone.now()
        candidates = AgentExecution.objects.filter(
            status__in=_ACTIVE_STATUSES,
            usage_reservation_expires_at__lt=current,
        )
        if user is not None:
            candidates = candidates.filter(conversation__user=user)
        reclaimed = []
        for execution in candidates.order_by("id"):
            sealed = self._seal(execution.id, now=current, require_lapsed_lease=True)
            if sealed is not None:
                reclaimed.append(sealed)
        return reclaimed

    def seal_lost(self, execution: AgentExecution) -> bool:
        """Fail one active execution whose worker the caller knows is gone."""
        return (
            self._seal(execution.id, now=timezone.now(), require_lapsed_lease=False)
            is not None
        )

    def _seal(self, execution_id: int, *, now, require_lapsed_lease: bool):
        # Re-checked under the row lock: a slow worker may have renewed since the scan.
        lease_filter = (
            {"usage_reservation_expires_at__lt": now} if require_lapsed_lease else {}
        )
        with transaction.atomic():
            locked = (
                AgentExecution.objects.select_for_update()
                .filter(id=execution_id, status__in=_ACTIVE_STATUSES, **lease_filter)
                .first()
            )
            if locked is None:
                return None
            if locked.status == AgentExecution.Status.PENDING:
                # Claim then fail, as an undeliverable turn is: only RUNNING seals.
                recorder = self.executions.claim_pending(locked)
            else:
                recorder = self.recorder_factory(locked)
            if recorder is None or not recorder.on_run_failed(WorkerLostError()):
                return None
            reconcile_stopped_run(locked)
        locked.refresh_from_db()
        logger.warning(
            "reclaimed an agent execution whose worker was lost",
            extra={
                "execution_id": locked.id,
                "conversation_id": locked.conversation_id,
            },
        )
        return locked
