"""Services for funding and grant overview dashboard metrics."""
from django.db.models import Case, Count, IntegerField, When
from django.utils import timezone

from purchase.models import Fundraise, Grant, GrantApplication, Purchase
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.usd_fundraise_contribution_model import UsdFundraiseContribution
from purchase.utils import get_funded_fundraise_ids, rsc_and_cents_to_usd
from user.models import User


class _OverviewMixin:
    """Shared query helpers for overview services."""

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


class FundingOverviewService(_OverviewMixin):
    """Service for calculating funding portfolio dashboard metrics for grant creators."""

    def get_funding_overview(self, user: User) -> dict:
        """Return funding overview metrics for a given user."""
        user_applications = GrantApplication.objects.for_user_grants(user)
        grant_fundraise_ids = user_applications.fundraise_ids()
        user_funded_ids = get_funded_fundraise_ids(user.id)
        funded_grant_proposals = list(grant_fundraise_ids & user_funded_ids)

        exchange_rate = RscExchangeRate.get_latest_exchange_rate()
        total_distributed = self._user_contributions_usd(
            user.id, list(grant_fundraise_ids), exchange_rate
        )
        matched_funding = self._matched_contributions_usd(
            user.id, funded_grant_proposals, exchange_rate
        )

        return {
            "total_distributed_usd": round(total_distributed, 2),
            "active_grants": self._active_grants(user),
            "total_applicants": self._count_applicants(user),
            "matched_funding_usd": round(matched_funding, 2),
            "proposals_funded": len(funded_grant_proposals),
        }

    def _count_applicants(self, user: User) -> dict:
        """Count total proposals attached to user's grants."""
        result = GrantApplication.objects.for_user_grants(user).aggregate(
            total=Count("preregistration_post_id", distinct=True),
            active=Count(
                Case(
                    When(
                        preregistration_post__unified_document__fundraises__status=Fundraise.OPEN,
                        then="preregistration_post_id",
                    ),
                    output_field=IntegerField(),
                ),
                distinct=True,
            ),
        )
        return {
            "total": result["total"],
            "active": result["active"],
            "previous": result["total"] - result["active"],
        }

    def _active_grants(self, user: User) -> dict:
        """Count active and total grants created by the user."""
        now = timezone.now()
        user_grants = Grant.objects.filter(created_by=user)
        result = user_grants.aggregate(
            total=Count("id"),
            active=Count(
                Case(
                    When(
                        status=Grant.OPEN,
                        end_date__isnull=True,
                        then=1,
                    ),
                    When(
                        status=Grant.OPEN,
                        end_date__gt=now,
                        then=1,
                    ),
                    output_field=IntegerField(),
                )
            ),
        )
        return {"active": result["active"], "total": result["total"]}


class GrantOverviewService(_OverviewMixin):
    """Service for calculating grant-specific dashboard metrics."""

    def get_grant_overview(self, user: User, grant: Grant) -> dict:
        """Return metrics for a specific grant."""
        applications = GrantApplication.objects.filter(grant=grant)
        fundraise_ids = list(
            applications.exclude(
                preregistration_post__unified_document__fundraises__id__isnull=True
            ).values_list(
                "preregistration_post__unified_document__fundraises__id", flat=True
            ).distinct()
        )
        user_funded_ids = get_funded_fundraise_ids(user.id)
        funded_fundraise_ids = list(set(fundraise_ids) & user_funded_ids)

        exchange_rate = RscExchangeRate.get_latest_exchange_rate()

        return {
            "budget_used_usd": round(
                self._user_contributions_usd(user.id, fundraise_ids, exchange_rate), 2
            ),
            "budget_total_usd": float(grant.amount),
            "matched_funding_usd": round(
                self._matched_contributions_usd(user.id, funded_fundraise_ids, exchange_rate), 2
            ),
            "total_proposals": applications.count(),
            "proposals_funded": len(funded_fundraise_ids),
            "deadline": grant.end_date,
        }
