import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from researchhub.celery import QUEUE_CACHES, app
from user.management.commands.setup_bank_user import BANK_EMAIL
from user.models import User
from user.related_models.funding_activity_model import (
    FundingActivity,
    FundingActivityRecipient,
)
from user.related_models.leaderboard_model import Leaderboard
from user.related_models.user_model import FOUNDATION_EMAIL

logger = logging.getLogger(__name__)


def _get_period_date_range(period):
    """
    Get start_date and end_date for a given period.
    Returns (start_date, end_date) tuple, where end_date is always now.
    For ALL_TIME, start_date is None (no filter).
    """
    now = timezone.now()
    if period == Leaderboard.SEVEN_DAYS:
        return now - timedelta(days=7), now
    elif period == Leaderboard.THIRTY_DAYS:
        return now - timedelta(days=30), now
    elif period == Leaderboard.SIX_MONTHS:
        return now - timedelta(days=180), now  # ~6 months
    elif period == Leaderboard.ONE_YEAR:
        return now - timedelta(days=365), now
    elif period == Leaderboard.ALL_TIME:
        return None, now
    else:
        raise ValueError(f"Unknown period: {period}")


def _get_excluded_user_ids():
    """Get user IDs to exclude from leaderboards."""
    excluded_emails = [BANK_EMAIL, FOUNDATION_EMAIL]
    return list(
        User.objects.filter(email__in=excluded_emails).values_list("id", flat=True)
    )


@app.task(queue=QUEUE_CACHES, max_retries=3, retry_backoff=True)
def refresh_leaderboard_task():
    """
    Refresh leaderboard data for all periods and types.
    Aggregates FundingActivity and FundingActivityRecipient data,
    calculates ranks, and writes to Leaderboard table.
    """
    excluded_user_ids = _get_excluded_user_ids()
    periods = [
        Leaderboard.SEVEN_DAYS,
        Leaderboard.THIRTY_DAYS,
        Leaderboard.SIX_MONTHS,
        Leaderboard.ONE_YEAR,
        Leaderboard.ALL_TIME,
    ]

    logger.info("refresh_leaderboard_task: Starting leaderboard refresh")

    with transaction.atomic():
        # Refresh funder leaderboards
        for period in periods:
            _refresh_funder_leaderboard(period, excluded_user_ids)

        # Refresh earner leaderboards
        for period in periods:
            _refresh_earner_leaderboard(period, excluded_user_ids)

    logger.info("refresh_leaderboard_task: Completed leaderboard refresh")


def _refresh_funder_leaderboard(period, excluded_user_ids):
    """Refresh funder leaderboard for a given period."""
    start_date, end_date = _get_period_date_range(period)

    # Aggregate FundingActivity by funder
    qs = FundingActivity.objects.exclude(funder_id__in=excluded_user_ids)

    if start_date:
        qs = qs.filter(activity_date__gte=start_date, activity_date__lte=end_date)

    funder_totals = (
        qs.values("funder_id")
        .annotate(total_amount=Sum("total_amount"))
        .order_by("-total_amount")
    )

    # Delete existing entries for this period and type
    Leaderboard.objects.filter(
        leaderboard_type=Leaderboard.FUNDER, period=period
    ).delete()

    # Create new entries with ranks
    rank = 1
    entries_to_create = []
    for entry in funder_totals:
        entries_to_create.append(
            Leaderboard(
                user_id=entry["funder_id"],
                leaderboard_type=Leaderboard.FUNDER,
                period=period,
                rank=rank,
                total_amount=entry["total_amount"],
            )
        )
        rank += 1

    if entries_to_create:
        Leaderboard.objects.bulk_create(entries_to_create)
        logger.info(
            f"refresh_leaderboard_task: Created {len(entries_to_create)} "
            f"funder entries for period {period}"
        )


def _refresh_earner_leaderboard(period, excluded_user_ids):
    """Refresh earner leaderboard for a given period."""
    start_date, end_date = _get_period_date_range(period)

    # Aggregate FundingActivityRecipient by recipient_user
    # Join with FundingActivity to filter by activity_date
    qs = FundingActivityRecipient.objects.select_related("activity").exclude(
        recipient_user_id__in=excluded_user_ids
    )

    if start_date:
        qs = qs.filter(
            activity__activity_date__gte=start_date,
            activity__activity_date__lte=end_date,
        )

    earner_totals = (
        qs.values("recipient_user_id")
        .annotate(total_amount=Sum("amount"))
        .order_by("-total_amount")
    )

    # Delete existing entries for this period and type
    Leaderboard.objects.filter(
        leaderboard_type=Leaderboard.EARNER, period=period
    ).delete()

    # Create new entries with ranks
    rank = 1
    entries_to_create = []
    for entry in earner_totals:
        entries_to_create.append(
            Leaderboard(
                user_id=entry["recipient_user_id"],
                leaderboard_type=Leaderboard.EARNER,
                period=period,
                rank=rank,
                total_amount=entry["total_amount"],
            )
        )
        rank += 1

    if entries_to_create:
        Leaderboard.objects.bulk_create(entries_to_create)
        logger.info(
            f"refresh_leaderboard_task: Created {len(entries_to_create)} "
            f"earner entries for period {period}"
        )
