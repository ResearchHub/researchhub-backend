from django.db.models import F, FloatField, Q, QuerySet, Sum
from django.db.models.functions import Cast, Coalesce

from purchase.models import Purchase
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from purchase.utils import rsc_and_cents_to_usd


class OverviewMixin:
    """Shared query helpers for funding and grant overview services."""

    def _query_user_contributions(
        self, user_id: int, fundraise_ids: list[int]
    ) -> tuple[float, int, float]:
        """Raw RSC total, USD cents, and RSC-to-USD snapshot for the user."""
        if not fundraise_ids:
            return 0.0, 0, 0.0
        rsc, snapshot = self._sum_rsc_with_snapshot(
            Purchase.objects.for_user(user_id)
            .funding_contributions()
            .for_fundraises(fundraise_ids)
        )
        cents = (
            UsdFundraiseContribution.objects.for_user(user_id)
            .not_refunded()
            .for_fundraises(fundraise_ids)
            .sum_cents()
        )
        return rsc, cents, snapshot

    def _query_matched_contributions(
        self, user_id: int, fundraise_ids: list[int]
    ) -> tuple[float, int, float]:
        """Raw RSC total, USD cents, and RSC-to-USD snapshot from others (excluding user)."""
        if not fundraise_ids:
            return 0.0, 0, 0.0
        rsc, snapshot = self._sum_rsc_with_snapshot(
            Purchase.objects.funding_contributions()
            .for_fundraises(fundraise_ids)
            .exclude_user(user_id)
        )
        cents = (
            UsdFundraiseContribution.objects.not_refunded()
            .for_fundraises(fundraise_ids)
            .exclude_user(user_id)
            .sum_cents()
        )
        return rsc, cents, snapshot

    @staticmethod
    def _sum_rsc_with_snapshot(queryset: QuerySet) -> tuple[float, float]:
        """
        Aggregate the RSC total and its USD snapshot for a Purchase queryset.

        The USD snapshot uses each contribution's `rsc_usd_rate` captured at the
        time of contribution. For older contributions where it was not captured,
        the latest exchange rate is used as a fallback.
        """
        aggregates = queryset.annotate(
            amount_float=Cast("amount", FloatField()),
        ).aggregate(
            rsc_total=Coalesce(Sum("amount_float"), 0.0),
            snapshot_with_rate=Coalesce(
                Sum(
                    F("amount_float") * F("rsc_usd_rate"),
                    filter=Q(rsc_usd_rate__isnull=False),
                    output_field=FloatField(),
                ),
                0.0,
            ),
            rsc_without_rate=Coalesce(
                Sum("amount_float", filter=Q(rsc_usd_rate__isnull=True)),
                0.0,
            ),
        )
        rsc = aggregates["rsc_total"]
        snapshot = aggregates["snapshot_with_rate"]
        rsc_without_rate = aggregates["rsc_without_rate"]
        if rsc_without_rate > 0:
            snapshot += RscExchangeRate.rsc_to_usd(rsc_without_rate)
        return rsc, snapshot

    def _user_contributions_usd(
        self, user_id: int, fundraise_ids: list[int], exchange_rate: float
    ) -> float:
        """Total contributions by a user to the given fundraises, in USD."""
        rsc, cents, _ = self._query_user_contributions(user_id, fundraise_ids)
        return rsc_and_cents_to_usd(rsc, cents, exchange_rate)

    def _matched_contributions_usd(
        self, user_id: int, fundraise_ids: list[int], exchange_rate: float
    ) -> float:
        """Total contributions from others (excluding user) to the given fundraises, in USD."""
        rsc, cents, _ = self._query_matched_contributions(user_id, fundraise_ids)
        return rsc_and_cents_to_usd(rsc, cents, exchange_rate)

    def _user_contributions_breakdown(
        self, user_id: int, fundraise_ids: list[int]
    ) -> dict:
        """Separate RSC, USD snapshot of RSC, and USD contribution totals by a user."""
        rsc, cents, snapshot = self._query_user_contributions(user_id, fundraise_ids)
        return {
            "rsc": round(rsc, 2),
            "rsc_usd_snapshot": round(snapshot, 2),
            "usd": round(cents / 100, 2),
        }

    def _matched_contributions_breakdown(
        self, user_id: int, fundraise_ids: list[int]
    ) -> dict:
        """Separate RSC, USD snapshot of RSC, and USD contribution totals from others (excluding user)."""
        rsc, cents, snapshot = self._query_matched_contributions(user_id, fundraise_ids)
        return {
            "rsc": round(rsc, 2),
            "rsc_usd_snapshot": round(snapshot, 2),
            "usd": round(cents / 100, 2),
        }

    def _per_fundraise_user_contributions(
        self, user_id: int, fundraise_ids: list[int]
    ) -> dict[int, dict]:
        """Per-fundraise {rsc, rsc_usd_snapshot, usd} for user."""
        if not fundraise_ids:
            return {}

        rsc_qs = (
            Purchase.objects.for_user(user_id)
            .funding_contributions()
            .for_fundraises(fundraise_ids)
            .annotate(amount_float=Cast("amount", FloatField()))
            .values("object_id")
            .annotate(
                rsc_total=Coalesce(Sum("amount_float"), 0.0),
                snapshot_with_rate=Coalesce(
                    Sum(
                        F("amount_float") * F("rsc_usd_rate"),
                        filter=Q(rsc_usd_rate__isnull=False),
                        output_field=FloatField(),
                    ),
                    0.0,
                ),
                rsc_without_rate=Coalesce(
                    Sum("amount_float", filter=Q(rsc_usd_rate__isnull=True)),
                    0.0,
                ),
            )
        )

        usd_qs = (
            UsdFundraiseContribution.objects.for_user(user_id)
            .not_refunded()
            .for_fundraises(fundraise_ids)
            .values("fundraise_id")
            .annotate(total_cents=Coalesce(Sum("amount_cents"), 0))
        )

        result: dict[int, dict] = {}
        for row in rsc_qs:
            fid = row["object_id"]
            snapshot = row["snapshot_with_rate"]
            if row["rsc_without_rate"] > 0:
                snapshot += RscExchangeRate.rsc_to_usd(row["rsc_without_rate"])
            result[fid] = {
                "rsc": round(row["rsc_total"], 2),
                "rsc_usd_snapshot": round(snapshot, 2),
                "usd": 0.0,
            }

        for row in usd_qs:
            fid = row["fundraise_id"]
            entry = result.setdefault(
                fid, {"rsc": 0.0, "rsc_usd_snapshot": 0.0, "usd": 0.0}
            )
            entry["usd"] = round(row["total_cents"] / 100, 2)

        return result
