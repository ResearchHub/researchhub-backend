"""Live totals and challenge progress for giving campaigns."""

from datetime import datetime
from typing import Any

from django.db.models import QuerySet

from purchase.models import Fundraise, GivingCampaign, GivingChallenge, Purchase
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from purchase.services.overview_mixin import OverviewMixin

Gifts = tuple[QuerySet[Purchase], QuerySet[UsdFundraiseContribution]]


class GivingCampaignService(OverviewMixin):
    """Totals a giving campaign's gifts and tracks each challenge's progress."""

    def summarize_campaign(self, campaign: GivingCampaign) -> dict:
        """Return the campaign's goal, gift totals and challenge progress."""
        rsc_gifts, usd_gifts = self._find_gifts(**self._build_window_filters(campaign))
        return {
            "slug": campaign.slug,
            "start_date": campaign.start_date,
            "end_date": campaign.end_date,
            "goal_usd": campaign.goal_usd,
            "given_usd": self._sum_gifts_usd(rsc_gifts, usd_gifts),
            "donor_count": len(self._collect_donor_ids(rsc_gifts, usd_gifts)),
            "featured_grant": campaign.featured_grant,
            "challenges": [
                self._summarize_challenge(challenge)
                for challenge in campaign.challenges.all()
            ],
        }

    def _summarize_challenge(self, challenge: GivingChallenge) -> dict:
        """Return the challenge with its matched dollars or its donor count."""
        summary = {
            "id": challenge.id,
            "kind": challenge.kind,
            "name": challenge.name,
            "sponsor": challenge.sponsor,
            "hub": challenge.hub,
            "amount_usd": challenge.amount_usd,
            "donor_goal": challenge.donor_goal,
            "first_time_donors_only": challenge.first_time_donors_only,
            "start_date": challenge.start_date,
            "end_date": challenge.end_date,
            "matched_usd": None,
            "donor_count": None,
        }
        if challenge.kind == GivingChallenge.Kind.MATCH:
            cap_usd = float(challenge.amount_usd)
            matched_usd = min(self._sum_hub_gifts_usd(challenge), cap_usd)
            return {
                **summary,
                "matched_usd": matched_usd,
                "is_completed": matched_usd == cap_usd,
            }
        donor_ids = self._collect_donor_ids(
            *self._find_gifts(**self._build_window_filters(challenge))
        )
        if challenge.first_time_donors_only:
            donor_ids = self._collect_first_time_donor_ids(
                donor_ids, challenge.start_date
            )
        donor_count = len(donor_ids)
        return {
            **summary,
            "donor_count": donor_count,
            "is_completed": donor_count >= challenge.donor_goal,
        }

    def _sum_hub_gifts_usd(self, challenge: GivingChallenge) -> float:
        """Total the challenge window's gifts to proposals in the challenge's hub."""
        fundraise_ids = list(
            Fundraise.objects.filter(unified_document__hubs=challenge.hub).values_list(
                "id", flat=True
            )
        )
        window_filters = self._build_window_filters(challenge)
        return self._sum_gifts_usd(
            Purchase.objects.funding_contributions()
            .for_fundraises(fundraise_ids)
            .filter(**window_filters),
            UsdFundraiseContribution.objects.not_refunded()
            .for_fundraises(fundraise_ids)
            .filter(**window_filters),
        )

    def _collect_first_time_donor_ids(
        self, donor_ids: set[int], start: datetime
    ) -> set[int]:
        """Keep the donors who had never given before the start."""
        return donor_ids - self._collect_donor_ids(
            *self._find_gifts(created_date__lt=start, user_id__in=donor_ids)
        )

    def _sum_gifts_usd(
        self,
        rsc_gifts: QuerySet[Purchase],
        usd_gifts: QuerySet[UsdFundraiseContribution],
    ) -> float:
        """Total RSC gifts at their rate when given, plus USD gifts, in USD."""
        _, rsc_usd = self._sum_rsc_with_snapshot(rsc_gifts)
        return round(rsc_usd + usd_gifts.sum_cents() / 100, 2)

    @staticmethod
    def _collect_donor_ids(
        rsc_gifts: QuerySet[Purchase],
        usd_gifts: QuerySet[UsdFundraiseContribution],
    ) -> set[int]:
        """Collect the distinct users behind the gifts."""
        return set(rsc_gifts.values_list("user_id", flat=True)) | set(
            usd_gifts.values_list("user_id", flat=True)
        )

    @staticmethod
    def _find_gifts(**filters: Any) -> Gifts:
        """Find RSC gifts to proposals and RFP pools, and USD gifts to proposals."""
        rsc_gifts = (
            Purchase.objects.funding_contributions()
            | Purchase.objects.funding_pool_contributions()
        ).filter(**filters)
        usd_gifts = UsdFundraiseContribution.objects.not_refunded().filter(**filters)
        return rsc_gifts, usd_gifts

    @staticmethod
    def _build_window_filters(
        dated: GivingCampaign | GivingChallenge,
    ) -> dict[str, datetime]:
        """Build the filters that keep gifts made between its start and end."""
        return {"created_date__gte": dated.start_date, "created_date__lt": dated.end_date}
