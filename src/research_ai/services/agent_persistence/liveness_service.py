"""Liveness sweeps and cooperative cancellation for agent executions.

``last_activity_at`` is a heartbeat. The recorder stamps it on every durable
write -- each context message, each trace row, the terminal transition -- so a
run that is genuinely working touches it at least once per model turn. Nothing
read it before this module.

Reading it imposes a contract on everything that creates an execution: **a
healthy ``RUNNING`` row must be touched more often than the heartbeat timeout,
including during work that writes no trace rows.** Inside the agent loop this
holds for free. Around it, it does not: an execution created before a long setup
phase looks abandoned for the whole of that phase. A caller doing such work
either keeps it under the timeout or calls
:meth:`DatabaseAgentRecorder.heartbeat` -- which exists for exactly this -- and
the timeout below is sized for the longest such gap in the codebase rather than
for one model turn. Getting this wrong reclaims a working run, whose next write
then raises ``InterruptedError`` and fails it, so the timeout errs long.

That matters because a worker can die between claiming an execution and
recording its terminal status: a deploy, an OOM kill, a lost broker connection.
The row stays ``RUNNING``, and since a linear conversation permits only one
active execution (``ra_agent_exec_one_active``), every later turn on that
conversation is refused as busy -- permanently. A queued attempt the broker
never delivered strands a conversation the same way while sitting ``PENDING``.
The sweep here is what unsticks both.

Cancellation rides the same seam and is deliberately cooperative. Marking a
``RUNNING`` execution ``CANCELLED`` from the request path does not reach into
the worker; the worker notices at its next durable write, where the recorder
refuses to append to a terminal execution and raises ``InterruptedError``, and
the run unwinds through its ordinary failure path. A ``PENDING`` execution
cancels even more simply: the claim is a conditional update on ``PENDING``, so
a task delivered afterwards finds nothing to claim and skips.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from research_ai.models import AgentExecution

logger = logging.getLogger(__name__)

# Sized to the longest gap a *healthy* run can leave, which is not one model
# turn. Inside the agent loop every turn and tool result lands a row, so the gap
# is minutes at most. Around the loop it is bounded only by whatever a caller
# does between creating the execution and driving it: proposal drafting builds a
# researcher profile there, itself an agent run of up to 16 tool turns writing
# no rows against this execution. One hour leaves that ample room. Being
# generous costs only how long a genuinely stuck conversation waits to recover,
# which beats reclaiming a run that was working.
DEFAULT_HEARTBEAT_TIMEOUT = timedelta(minutes=60)
DEFAULT_QUEUE_TIMEOUT = timedelta(minutes=30)

_HEARTBEAT_TIMEOUT_SETTING = "RESEARCH_AI_AGENT_HEARTBEAT_TIMEOUT_SECONDS"
_QUEUE_TIMEOUT_SETTING = "RESEARCH_AI_AGENT_QUEUE_TIMEOUT_SECONDS"

# Recorded on the reclaimed row so a stalled run is distinguishable after the
# fact from one that failed while someone was still driving it.
STALLED_ERROR_TYPE = "AgentHeartbeatLost"
STALLED_STOP_REASON = "stalled"
NEVER_STARTED_ERROR_TYPE = "AgentNeverStarted"
NEVER_STARTED_STOP_REASON = "never_started"
CANCELLED_STOP_REASON = "cancelled"


@dataclass(frozen=True)
class ReclaimedExecutions:
    """How many rows one sweep unstuck, by why they were stuck."""

    stalled: int = 0
    never_started: int = 0

    @property
    def total(self) -> int:
        return self.stalled + self.never_started


def _timeout_from_settings(name: str, default: timedelta) -> timedelta:
    """Read a timeout at call time so ``override_settings`` applies per test."""
    seconds = getattr(settings, name, None)
    return default if seconds is None else timedelta(seconds=seconds)


class AgentLivenessService:
    """Reclaim executions nobody is driving, and cancel ones on request."""

    def __init__(
        self,
        *,
        heartbeat_timeout: timedelta | None = None,
        queue_timeout: timedelta | None = None,
    ):
        self._heartbeat_timeout = heartbeat_timeout
        self._queue_timeout = queue_timeout

    @property
    def heartbeat_timeout(self) -> timedelta:
        if self._heartbeat_timeout is not None:
            return self._heartbeat_timeout
        return _timeout_from_settings(
            _HEARTBEAT_TIMEOUT_SETTING, DEFAULT_HEARTBEAT_TIMEOUT
        )

    @property
    def queue_timeout(self) -> timedelta:
        if self._queue_timeout is not None:
            return self._queue_timeout
        return _timeout_from_settings(_QUEUE_TIMEOUT_SETTING, DEFAULT_QUEUE_TIMEOUT)

    # -- sweep ------------------------------------------------------------

    def reclaim_stalled(self) -> ReclaimedExecutions:
        """Mark every abandoned active execution ``INTERRUPTED``.

        Candidates are selected without a lock and then re-checked under one,
        because the scan races the very workers it is looking for: a run that
        wrote a heartbeat between the two steps is healthy and left alone.
        """
        now = timezone.now()
        stalled = self._reclaim_all(
            self._stalled_ids(now - self.heartbeat_timeout),
            expected_status=AgentExecution.Status.RUNNING,
            cutoff=now - self.heartbeat_timeout,
            error_type=STALLED_ERROR_TYPE,
            stop_reason=STALLED_STOP_REASON,
            error_message=(
                "The worker driving this execution stopped reporting activity."
            ),
        )
        never_started = self._reclaim_all(
            self._never_started_ids(now - self.queue_timeout),
            expected_status=AgentExecution.Status.PENDING,
            cutoff=now - self.queue_timeout,
            error_type=NEVER_STARTED_ERROR_TYPE,
            stop_reason=NEVER_STARTED_STOP_REASON,
            error_message="The queued execution was never claimed by a worker.",
        )
        reclaimed = ReclaimedExecutions(stalled=stalled, never_started=never_started)
        if reclaimed.total:
            logger.warning(
                "reclaimed abandoned agent executions",
                extra={
                    "stalled": reclaimed.stalled,
                    "never_started": reclaimed.never_started,
                },
            )
        return reclaimed

    @staticmethod
    def _stalled_ids(cutoff: datetime) -> list[int]:
        return list(
            AgentExecution.objects.filter(
                status=AgentExecution.Status.RUNNING,
            )
            .filter(_heartbeat_before(cutoff))
            .values_list("id", flat=True)
        )

    @staticmethod
    def _never_started_ids(cutoff: datetime) -> list[int]:
        return list(
            AgentExecution.objects.filter(
                status=AgentExecution.Status.PENDING,
                created_date__lt=cutoff,
            ).values_list("id", flat=True)
        )

    def _reclaim_all(self, execution_ids: list[int], **terminal) -> int:
        return sum(
            int(self._reclaim_one(execution_id, **terminal))
            for execution_id in execution_ids
        )

    @staticmethod
    def _reclaim_one(
        execution_id: int,
        *,
        expected_status: str,
        cutoff: datetime,
        error_type: str,
        stop_reason: str,
        error_message: str,
    ) -> bool:
        with transaction.atomic():
            execution = (
                AgentExecution.objects.select_for_update()
                .filter(id=execution_id, status=expected_status)
                .first()
            )
            # Gone, or already terminal: the worker landed its own outcome while
            # this sweep was walking the candidate list.
            if execution is None:
                return False
            if _heartbeat_of(execution) >= cutoff:
                return False
            now = timezone.now()
            execution.status = AgentExecution.Status.INTERRUPTED
            execution.error_type = error_type
            execution.error_message = error_message
            execution.error_details = {"stop_reason": stop_reason, "reclaimed": True}
            execution.stop_reason = stop_reason
            execution.finished_at = now
            execution.last_activity_at = now
            if execution.started_at is not None:
                execution.duration_ms = max(
                    0, round((now - execution.started_at).total_seconds() * 1000)
                )
            execution.save(
                update_fields=[
                    "status",
                    "error_type",
                    "error_message",
                    "error_details",
                    "stop_reason",
                    "finished_at",
                    "last_activity_at",
                    "duration_ms",
                    "updated_date",
                ]
            )
            return True

    # -- cancellation -----------------------------------------------------

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


def _heartbeat_of(execution: AgentExecution) -> datetime:
    """The most recent sign of life, however coarse.

    ``last_activity_at`` is set the moment an execution goes ``RUNNING`` and on
    every write after, so the fallbacks only matter for a ``PENDING`` row (no
    activity yet) or a row predating that guarantee.
    """
    return execution.last_activity_at or execution.started_at or execution.created_date


def _heartbeat_before(cutoff: datetime) -> Q:
    """Match rows whose heartbeat -- or its fallbacks -- predates ``cutoff``."""
    return (
        Q(last_activity_at__lt=cutoff)
        | Q(last_activity_at__isnull=True, started_at__lt=cutoff)
        | Q(
            last_activity_at__isnull=True,
            started_at__isnull=True,
            created_date__lt=cutoff,
        )
    )
