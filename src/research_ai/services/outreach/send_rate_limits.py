"""Per-mailbox daily caps for Expert Finder Gmail outreach sends.

Quota resets at 00:00. ``SENT`` today and every outstanding ``SENDING`` row
count so queued bulk reservations consume the budget even across that
cutoff. A send request that exceeds remaining quota is rejected entirely
(nothing queued). See ``send_pacing`` for bulk inter-send gaps.

Follow-up (not implemented): sync Gmail bounce / delivery / reply state into
``GeneratedEmail`` statuses beyond the legacy SES handlers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from research_ai.constants import OUTREACH_SEND_DAILY_CAP_DEFAULT
from research_ai.models import GeneratedEmail

RATE_LIMIT_CODE = "outreach_rate_limited"
BULK_IN_PROGRESS_CODE = "outreach_bulk_in_progress"


def _cap(name: str, default: int) -> int:
    return max(0, int(getattr(settings, name, default)))


def _today_start():
    return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class SendQuota:
    """Remaining send slots for one mailbox owner."""

    used_day: int
    daily_cap: int

    @property
    def remaining_day(self) -> int:
        return max(0, self.daily_cap - self.used_day)


def get_send_quota(user) -> SendQuota:
    """
    Count today's SENT outreach plus every outstanding SENDING reservation.

    ``SENDING`` still occupies a slot until it sends or fails, including rows
    reserved before 00:00. Mailbox ownership is 1:1 with the editor user, so
    ``created_by`` matches the connected Gmail account used on send.
    """
    daily_cap = _cap("OUTREACH_SEND_DAILY_CAP", OUTREACH_SEND_DAILY_CAP_DEFAULT)
    start = _today_start()
    used_day = (
        GeneratedEmail.objects.filter(created_by=user)
        .filter(
            Q(status=GeneratedEmail.Status.SENDING)
            | Q(status=GeneratedEmail.Status.SENT, updated_date__gte=start)
        )
        .count()
    )
    return SendQuota(used_day=used_day, daily_cap=daily_cap)


def get_daily_usage(user) -> dict:
    """Usage breakdown for mailbox status."""
    daily_cap = _cap("OUTREACH_SEND_DAILY_CAP", OUTREACH_SEND_DAILY_CAP_DEFAULT)
    start = _today_start()
    counts = GeneratedEmail.objects.filter(created_by=user).aggregate(
        sent_today=Count(
            "id",
            filter=Q(
                status=GeneratedEmail.Status.SENT,
                updated_date__gte=start,
            ),
        ),
        queued_today=Count(
            "id",
            filter=Q(status=GeneratedEmail.Status.SENDING),
        ),
    )
    sent_today = counts["sent_today"]
    queued_today = counts["queued_today"]
    return {
        "daily_cap": daily_cap,
        "sent_today": sent_today,
        "queued_today": queued_today,
        "remaining_today": max(0, daily_cap - sent_today - queued_today),
        "resets_at": (start + timedelta(days=1)).isoformat(),
    }


def editor_has_sending(user) -> bool:
    """True when this editor already has outreach rows in SENDING."""
    return GeneratedEmail.objects.filter(
        created_by=user,
        status=GeneratedEmail.Status.SENDING,
    ).exists()


def rate_limit_error_payload(quota: SendQuota, *, requested: int) -> dict:
    return {
        "detail": (
            f"Daily outreach limit is {quota.daily_cap}; you already used "
            f"{quota.used_day} today and requested {requested}. "
            f"Only {quota.remaining_day} remaining today."
        ),
        "code": RATE_LIMIT_CODE,
        "daily_cap": quota.daily_cap,
        "used_today": quota.used_day,
        "requested": requested,
        "remaining_today": quota.remaining_day,
    }


def bulk_in_progress_error_payload() -> dict:
    return {
        "detail": (
            "A bulk outreach send is already in progress for this mailbox. "
            "Wait for it to finish or send a single email."
        ),
        "code": BULK_IN_PROGRESS_CODE,
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
