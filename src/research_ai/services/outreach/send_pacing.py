"""Minimum gap between successful Gmail outreach sends per mailbox.

Caps alone still allow a burst of near-identical messages as fast as the API
allows. Pacing enforces ``OUTREACH_SEND_MIN_INTERVAL_SECONDS`` between
successful sends for the same editor (mailbox owner).

Preview sends do not mark ``GeneratedEmail`` as SENT, so they do not consume
this interval.
"""

from __future__ import annotations

import math
from datetime import datetime

from django.conf import settings
from django.utils import timezone

from research_ai.constants import OUTREACH_SEND_MIN_INTERVAL_SECONDS_DEFAULT
from research_ai.models import GeneratedEmail


def min_interval_seconds() -> int:
    return max(
        0,
        int(
            getattr(
                settings,
                "OUTREACH_SEND_MIN_INTERVAL_SECONDS",
                OUTREACH_SEND_MIN_INTERVAL_SECONDS_DEFAULT,
            )
        ),
    )


def get_last_successful_send_at(user) -> datetime | None:
    """
    Latest successful outreach send for this mailbox owner.

    Uses SENT only (not SENDING) so queue-time reservation does not start the
    pacing clock.
    """
    return (
        GeneratedEmail.objects.filter(
            created_by=user,
            status=GeneratedEmail.Status.SENT,
        )
        .order_by("-updated_date")
        .values_list("updated_date", flat=True)
        .first()
    )


def seconds_until_next_send(user) -> int:
    """Seconds to wait before the next Gmail send for ``user`` (0 if ready)."""
    interval = min_interval_seconds()
    if interval <= 0:
        return 0
    last = get_last_successful_send_at(user)
    if last is None:
        return 0
    elapsed = (timezone.now() - last).total_seconds()
    remaining = interval - elapsed
    if remaining <= 0:
        return 0
    return max(1, int(math.ceil(remaining)))
