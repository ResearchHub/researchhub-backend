"""Worker-side liveness heartbeat for Research AI budget reservations."""

import logging
import threading
from datetime import datetime, timedelta

from django.db import connection
from django.utils import timezone

from research_ai.services.usage_budget.reservation import (
    USAGE_RESERVATION_RENEW_INTERVAL,
    renew_live_reservation,
)

logger = logging.getLogger(__name__)

# How long ``stop`` waits for a beat already talking to the database.
_STOP_TIMEOUT_SECONDS = 5.0


class ReservationHeartbeat:
    """Renew budget leases from a background thread while a worker runs.

    Renewal is independent of loop progress: a process blocked in a long
    provider read keeps its lease, and a dead process loses it within one
    lease period. ``lost`` turns true once a beat finds no live lease to
    extend, after which the run must not start another provider call.
    """

    def __init__(
        self,
        targets,
        *,
        interval: timedelta = USAGE_RESERVATION_RENEW_INTERVAL,
        renew=renew_live_reservation,
    ):
        # Only rows holding a reservation take part; the rest have nothing to renew.
        self.targets = tuple(
            target
            for target in targets
            if target is not None and target.usage_reservation_expires_at is not None
        )
        self.interval = interval
        self._renew = renew
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.lost = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop()

    def start(self) -> None:
        if not self.targets or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="usage-reservation-heartbeat", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=_STOP_TIMEOUT_SECONDS)
            self._thread = None

    def beat(self, *, now: datetime | None = None) -> bool:
        """Renew every target once; ``False`` (and ``lost``) once a lease has lapsed."""
        current = now or timezone.now()
        alive = True
        for target in self.targets:
            try:
                renewed = self._renew(target, now=current)
            except Exception:  # noqa: BLE001 - the lease tolerates a missed beat
                logger.warning(
                    "usage reservation heartbeat failed",
                    extra={
                        "target_type": type(target).__name__,
                        "target_id": target.id,
                    },
                    exc_info=True,
                )
                continue
            if not renewed:
                alive = False
        if not alive:
            self.lost = True
        return alive

    def _run(self) -> None:
        try:
            while not self._stop.wait(self.interval.total_seconds()):
                self.beat()
        finally:
            # This thread's own connection; the task thread keeps its own.
            connection.close()
