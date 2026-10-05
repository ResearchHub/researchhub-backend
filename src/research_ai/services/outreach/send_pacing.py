"""Bulk Gmail outreach pacing: random gap between sends in a batch.

Single-id sends pass ``immediate=True`` into the Celery task and skip pacing.
Bulk batches (2+) send the first message when the worker runs, then re-queue
remaining rows with a random countdown in
``[OUTREACH_SEND_MIN_INTERVAL_SECONDS, OUTREACH_SEND_MAX_INTERVAL_SECONDS]``.

Preview sends do not mark ``GeneratedEmail`` as SENT, so they do not affect
pacing.
"""

from __future__ import annotations

import random

from research_ai.constants import (
    OUTREACH_SEND_MAX_INTERVAL_SECONDS,
    OUTREACH_SEND_MIN_INTERVAL_SECONDS,
)


def next_bulk_interval_seconds() -> int:
    """Random seconds to wait before the next message in a bulk batch."""
    lo = max(0, int(OUTREACH_SEND_MIN_INTERVAL_SECONDS))
    hi = max(0, int(OUTREACH_SEND_MAX_INTERVAL_SECONDS))
    if hi < lo:
        hi = lo
    if hi <= 0:
        return 0
    return random.randint(lo, hi)
