"""Renewable database leases for single-flight Research AI budget admission."""

from datetime import datetime, timedelta

from django.utils import timezone

from research_ai.models import AgentExecution, ProposalDraft

# A running worker renews its lease from a background heartbeat, independent of
# loop progress, so a dead worker is recognised within one lease period.
USAGE_RESERVATION_LEASE = timedelta(minutes=3)
USAGE_RESERVATION_RENEW_INTERVAL = timedelta(seconds=30)
# How long a queued job may wait for a worker to claim it before it is presumed lost.
USAGE_RESERVATION_CLAIM_DEADLINE = timedelta(minutes=30)

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
    """Return the expiry used for a newly claimed or renewed lease."""
    return (now or timezone.now()) + USAGE_RESERVATION_LEASE


def claim_deadline(now: datetime | None = None) -> datetime:
    """Return the expiry a queued job holds until a worker claims it."""
    return (now or timezone.now()) + USAGE_RESERVATION_CLAIM_DEADLINE


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
    """Extend an unexpired lease from a live worker's heartbeat.

    A cancelled row is deliberately permitted: a heartbeat after cancellation
    means the worker, and possibly its paid provider call, is still alive.
    Refusing an expired lease keeps a delayed zombie from reviving a slot that
    admission has already treated as released.
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
