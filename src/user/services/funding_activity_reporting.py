from django.db.models import FloatField, Q, QuerySet, Sum
from django.db.models.functions import Cast, Coalesce

from user.related_models.funding_activity_model import (
    FundingActivity,
    FundingActivityRecipient,
)

_ZERO_BREAKDOWN = {"rsc": 0.0, "rsc_usd_snapshot": 0.0, "usd": 0.0}

RSC_NATIVE_SOURCE_TYPES = frozenset(
    {
        FundingActivity.FUNDRAISE_PAYOUT,
        FundingActivity.BOUNTY_PAYOUT,
        FundingActivity.TIP_DOCUMENT,
        FundingActivity.TIP_REVIEW,
        FundingActivity.FEE,
    }
)

USD_NATIVE_SOURCE_TYPES = frozenset({FundingActivity.USD_FUNDRAISE_PAYOUT})

EARNER_SOURCE_TYPES = frozenset(
    {
        FundingActivity.FUNDRAISE_PAYOUT,
        FundingActivity.USD_FUNDRAISE_PAYOUT,
        FundingActivity.BOUNTY_PAYOUT,
        FundingActivity.TIP_DOCUMENT,
        FundingActivity.TIP_REVIEW,
    }
)


def _zero_breakdown() -> dict:
    return dict(_ZERO_BREAKDOWN)


def _breakdown_from_sums(
    rsc_total: float,
    rsc_native_usd_cents: int,
    usd_native_cents: int,
) -> dict:
    """Build {rsc, rsc_usd_snapshot, usd} from pre-aggregated sums."""
    return {
        "rsc": round(rsc_total, 2),
        "rsc_usd_snapshot": round(rsc_native_usd_cents / 100, 2),
        "usd": round(usd_native_cents / 100, 2),
    }


def _breakdown_for_source_type(
    source_type: str, rsc_total: float, usd_cents_total: int
) -> dict:
    """Build a single-source breakdown using native-leg semantics for that type."""
    if source_type in USD_NATIVE_SOURCE_TYPES:
        return _breakdown_from_sums(rsc_total, 0, usd_cents_total)
    return _breakdown_from_sums(rsc_total, usd_cents_total, 0)


def _merge_breakdowns(*breakdowns: dict) -> dict:
    """Sum multiple {rsc, rsc_usd_snapshot, usd} dicts."""
    rsc = 0.0
    rsc_usd_snapshot = 0.0
    usd = 0.0
    for breakdown in breakdowns:
        rsc += breakdown["rsc"]
        rsc_usd_snapshot += breakdown["rsc_usd_snapshot"]
        usd += breakdown["usd"]
    return {
        "rsc": round(rsc, 2),
        "rsc_usd_snapshot": round(rsc_usd_snapshot, 2),
        "usd": round(usd, 2),
    }


class FundingActivityReportingService:
    """Read-side breakdowns of precomputed FundingActivity amounts for UI/API."""

    @classmethod
    def earnings_for_user(
        cls,
        user_id: int,
        source_types: frozenset[str] | None = None,
        start_date=None,
        end_date=None,
    ) -> dict:
        """Return {total_earned, by_source} breakdowns for a recipient user."""
        if source_types is None:
            source_types = EARNER_SOURCE_TYPES
        qs = cls._recipient_queryset_for_user(
            user_id, source_types=source_types, start_date=start_date, end_date=end_date
        )
        by_source = cls._aggregate_recipients_by_source(qs)
        return {
            "total_earned": _merge_breakdowns(*by_source.values())
            if by_source
            else _zero_breakdown(),
            "by_source": by_source,
        }

    @classmethod
    def funding_for_user(
        cls,
        user_id: int,
        start_date=None,
        end_date=None,
    ) -> dict:
        """Return total funding breakdown for a funder user."""
        qs = FundingActivity.objects.filter(funder_id=user_id)
        if start_date is not None:
            qs = qs.filter(activity_date__gte=start_date)
        if end_date is not None:
            qs = qs.filter(activity_date__lte=end_date)
        return cls._aggregate_activity_queryset(qs)

    @classmethod
    def _aggregate_recipient_queryset(
        cls, queryset: QuerySet[FundingActivityRecipient]
    ) -> dict:
        """Sum amount and amount_usd_cents from a FundingActivityRecipient queryset."""
        aggregates = queryset.annotate(
            amount_float=Cast("amount", FloatField()),
        ).aggregate(
            rsc_total=Coalesce(Sum("amount_float"), 0.0),
            rsc_native_usd_cents=Coalesce(
                Sum(
                    "amount_usd_cents",
                    filter=Q(activity__source_type__in=RSC_NATIVE_SOURCE_TYPES),
                ),
                0,
            ),
            usd_native_cents=Coalesce(
                Sum(
                    "amount_usd_cents",
                    filter=Q(activity__source_type__in=USD_NATIVE_SOURCE_TYPES),
                ),
                0,
            ),
        )
        return _breakdown_from_sums(
            aggregates["rsc_total"],
            aggregates["rsc_native_usd_cents"],
            aggregates["usd_native_cents"],
        )

    @classmethod
    def _aggregate_activity_queryset(cls, queryset: QuerySet[FundingActivity]) -> dict:
        """Sum total_amount and total_usd_cents from a FundingActivity queryset."""
        aggregates = queryset.annotate(
            total_amount_float=Cast("total_amount", FloatField()),
        ).aggregate(
            rsc_total=Coalesce(Sum("total_amount_float"), 0.0),
            rsc_native_usd_cents=Coalesce(
                Sum(
                    "total_usd_cents",
                    filter=Q(source_type__in=RSC_NATIVE_SOURCE_TYPES),
                ),
                0,
            ),
            usd_native_cents=Coalesce(
                Sum(
                    "total_usd_cents",
                    filter=Q(source_type__in=USD_NATIVE_SOURCE_TYPES),
                ),
                0,
            ),
        )
        return _breakdown_from_sums(
            aggregates["rsc_total"],
            aggregates["rsc_native_usd_cents"],
            aggregates["usd_native_cents"],
        )

    @classmethod
    def _aggregate_recipients_by_source(
        cls, queryset: QuerySet[FundingActivityRecipient]
    ) -> dict[str, dict]:
        """Return per-source_type {rsc, rsc_usd_snapshot, usd} from recipients."""
        rows = (
            queryset.annotate(amount_float=Cast("amount", FloatField()))
            .values("activity__source_type")
            .annotate(
                rsc_total=Coalesce(Sum("amount_float"), 0.0),
                usd_cents_total=Coalesce(Sum("amount_usd_cents"), 0),
            )
            .order_by("activity__source_type")
        )
        return {
            row["activity__source_type"]: _breakdown_for_source_type(
                row["activity__source_type"],
                row["rsc_total"],
                row["usd_cents_total"],
            )
            for row in rows
        }

    @classmethod
    def _recipient_queryset_for_user(
        cls,
        user_id: int,
        source_types: frozenset[str] | None = None,
        start_date=None,
        end_date=None,
    ) -> QuerySet[FundingActivityRecipient]:
        qs = FundingActivityRecipient.objects.filter(recipient_user_id=user_id)
        if source_types is not None:
            qs = qs.filter(activity__source_type__in=source_types)
        if start_date is not None:
            qs = qs.filter(activity__activity_date__gte=start_date)
        if end_date is not None:
            qs = qs.filter(activity__activity_date__lte=end_date)
        return qs
