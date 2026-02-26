from purchase.models import Purchase
from purchase.related_models.usd_fundraise_contribution_model import UsdFundraiseContribution
from purchase.utils import rsc_and_cents_to_usd


class OverviewMixin:
    """Shared query helpers for funding and grant overview services."""

    def _query_user_contributions(
        self, user_id: int, fundraise_ids: list[int]
    ) -> tuple[float, int]:
        """Raw RSC total and USD cents contributed by user."""
        if not fundraise_ids:
            return 0.0, 0
        rsc = float(
            Purchase.objects.for_user(user_id)
            .funding_contributions()
            .for_fundraises(fundraise_ids)
            .sum()
        )
        cents = (
            UsdFundraiseContribution.objects.for_user(user_id)
            .not_refunded()
            .for_fundraises(fundraise_ids)
            .sum_cents()
        )
        return rsc, cents

    def _query_matched_contributions(
        self, user_id: int, fundraise_ids: list[int]
    ) -> tuple[float, int]:
        """Raw RSC total and USD cents contributed by others (excluding user)."""
        if not fundraise_ids:
            return 0.0, 0
        rsc = float(
            Purchase.objects.funding_contributions()
            .for_fundraises(fundraise_ids)
            .exclude_user(user_id)
            .sum()
        )
        cents = (
            UsdFundraiseContribution.objects.not_refunded()
            .for_fundraises(fundraise_ids)
            .exclude_user(user_id)
            .sum_cents()
        )
        return rsc, cents

    def _user_contributions_usd(
        self, user_id: int, fundraise_ids: list[int], exchange_rate: float
    ) -> float:
        """Total contributions by a user to the given fundraises, in USD."""
        rsc, cents = self._query_user_contributions(user_id, fundraise_ids)
        return rsc_and_cents_to_usd(rsc, cents, exchange_rate)

    def _matched_contributions_usd(
        self, user_id: int, fundraise_ids: list[int], exchange_rate: float
    ) -> float:
        """Total contributions from others (excluding user) to the given fundraises, in USD."""
        rsc, cents = self._query_matched_contributions(user_id, fundraise_ids)
        return rsc_and_cents_to_usd(rsc, cents, exchange_rate)

    def _user_contributions_breakdown(
        self, user_id: int, fundraise_ids: list[int]
    ) -> dict:
        """Separate RSC and USD contribution totals by a user."""
        rsc, cents = self._query_user_contributions(user_id, fundraise_ids)
        return {"rsc": round(rsc, 2), "usd": round(cents / 100, 2)}

    def _matched_contributions_breakdown(
        self, user_id: int, fundraise_ids: list[int]
    ) -> dict:
        """Separate RSC and USD contribution totals from others (excluding user)."""
        rsc, cents = self._query_matched_contributions(user_id, fundraise_ids)
        return {"rsc": round(rsc, 2), "usd": round(cents / 100, 2)}
