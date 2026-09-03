"""Renewable database leases for single-flight Research AI budget admission."""

from datetime import datetime, timedelta

from django.utils import timezone

from research_ai.models import AgentExecution, ProposalDraft

USAGE_RESERVATION_LEASE = timedelta(hours=2)
USAGE_RESERVATION_RENEW_INTERVAL = timedelta(minutes=10)

ReservationTarget = AgentExecution | ProposalDraft

_ACTIVE_STATUSES = {
    AgentExecution: (
        AgentExecution.Status.PENDING,
        AgentExecution.Status.RUNNING,
    ),
    ProposalDraft: (
        ProposalDraft.Status.PENDING,
        ProposalDraft.Status.PROCESSING,
    ),
}


def reservation_deadline(now: datetime | None = None) -> datetime:
    """Return the expiry used for a newly acquired or renewed lease."""
    return (now or timezone.now()) + USAGE_RESERVATION_LEASE


def renew_active_reservation(
    target: ReservationTarget, *, now: datetime | None = None
) -> bool:
    """Renew only while the worker still owns an active lifecycle row."""
    current = now or timezone.now()
    return bool(
        type(target)
        .objects.filter(
            id=target.id,
            status__in=_ACTIVE_STATUSES[type(target)],
        )
        .update(usage_reservation_expires_at=reservation_deadline(current))
    )


def renew_live_reservation(
    target: ReservationTarget, *, now: datetime | None = None
) -> bool:
    """Extend an unexpired lease while an already-started call emits activity.

    This deliberately permits a cancelled row: streaming after cancellation is
    proof that its worker and paid provider call are still alive. Requiring the
    old lease to remain current prevents a delayed zombie worker from reviving a
    reservation after admission has already treated it as expired.
    """
    current = now or timezone.now()
    return bool(
        type(target)
        .objects.filter(
            id=target.id,
            usage_reservation_expires_at__gt=current,
        )
        .update(usage_reservation_expires_at=reservation_deadline(current))
    )
