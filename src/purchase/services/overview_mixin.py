from purchase.models import Purchase
from purchase.related_models.usd_fundraise_contribution_model import UsdFundraiseContribution
from purchase.utils import rsc_and_cents_to_usd


class OverviewMixin:
    """Shared query helpers for funding and grant overview services."""

    def _user_contributions_usd(
        self, user_id: int, fundraise_ids: list[int], exchange_rate: float
    ) -> float:
        """Total contributions by a user to the given fundraises, in USD."""
        if not fundraise_ids:
            return 0.0
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
        return rsc_and_cents_to_usd(rsc, cents, exchange_rate)

    def _matched_contributions_usd(
        self, user_id: int, fundraise_ids: list[int], exchange_rate: float
    ) -> float:
        """Total contributions from others (excluding user) to the given fundraises, in USD."""
        if not fundraise_ids:
            return 0.0
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
        return rsc_and_cents_to_usd(rsc, cents, exchange_rate)

