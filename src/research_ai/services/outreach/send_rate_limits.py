"""Per-mailbox hourly/daily caps for Expert Finder Gmail outreach sends.

Defaults are aligned with send pacing (~1 send / 6 minutes → ~10/hour,
~100/day). See ``send_pacing`` for the inter-send gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from research_ai.constants import (
    OUTREACH_SEND_DAILY_CAP_DEFAULT,
    OUTREACH_SEND_HOURLY_CAP_DEFAULT,
)
from research_ai.models import GeneratedEmail

RATE_LIMIT_CODE = "outreach_rate_limited"


def _cap(name: str, default: int) -> int:
    return max(0, int(getattr(settings, name, default)))


@dataclass(frozen=True)
class SendQuota:
    """Remaining send slots for one mailbox owner."""

    used_hour: int
    used_day: int
    hourly_cap: int
    daily_cap: int

    @property
    def remaining_hour(self) -> int:
        return max(0, self.hourly_cap - self.used_hour)

    @property
    def remaining_day(self) -> int:
        return max(0, self.daily_cap - self.used_day)

    @property
    def remaining(self) -> int:
        """Slots available now (tighter of hourly and daily)."""
        return min(self.remaining_hour, self.remaining_day)


def get_send_quota(user) -> SendQuota:
    """
    Count SENT/SENDING outreach for ``user`` in the last hour and calendar day.

    Mailbox ownership is 1:1 with the editor user, so ``created_by`` matches
    the connected Gmail account used on send.
    """
    hourly_cap = _cap("OUTREACH_SEND_HOURLY_CAP", OUTREACH_SEND_HOURLY_CAP_DEFAULT)
    daily_cap = _cap("OUTREACH_SEND_DAILY_CAP", OUTREACH_SEND_DAILY_CAP_DEFAULT)
    now = timezone.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    hour_start = now - timedelta(hours=1)

    base = GeneratedEmail.objects.filter(
        created_by=user,
        status__in=(
            GeneratedEmail.Status.SENT,
            GeneratedEmail.Status.SENDING,
        ),
    )
    used_day = base.filter(updated_date__gte=day_start).count()
    used_hour = base.filter(updated_date__gte=hour_start).count()
    return SendQuota(
        used_hour=used_hour,
        used_day=used_day,
        hourly_cap=hourly_cap,
        daily_cap=daily_cap,
    )


def split_for_quota(
    generated_email_ids: list[int],
    remaining: int,
) -> tuple[list[int], list[int]]:
    """Return ``(to_queue, deferred)`` preserving input order."""
    if remaining <= 0:
        return [], list(generated_email_ids)
    return (
        list(generated_email_ids[:remaining]),
        list(generated_email_ids[remaining:]),
    )


def rate_limit_error_payload(quota: SendQuota) -> dict:
    return {
        "detail": "Outreach send limit reached for this mailbox.",
        "code": RATE_LIMIT_CODE,
        "remaining_today": quota.remaining_day,
        "remaining_hour": quota.remaining_hour,
    }


def queue_payload(
    *,
    queued_ids: list[int],
    deferred_ids: list[int],
    remaining_today: int,
) -> dict:
    return {
        "queued": len(queued_ids),
        "deferred": deferred_ids,
        "remaining_today": remaining_today,
    }
