"""Services for funding and grant overview dashboard metrics."""
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Case, Count, IntegerField, QuerySet, When
from django.utils import timezone

from purchase.models import Fundraise, Grant, GrantApplication, Purchase
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.usd_fundraise_contribution_model import UsdFundraiseContribution
from purchase.utils import get_funded_fundraise_ids, rsc_and_cents_to_usd
from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubPost
from user.models import User

RECENT_UPDATES_DAYS = 30


class _AuthorUpdateMixin:
    """Shared author-update query helpers for overview services."""

    def _recent_updates_qs(self, post_ids: list[int], days: int) -> QuerySet:
        """Return author update comments on the given posts within the time window."""
        post_ct = ContentType.objects.get_for_model(ResearchhubPost)
        return RhCommentModel.objects.filter(
            comment_type=AUTHOR_UPDATE,
            thread__content_type=post_ct,
            thread__object_id__in=post_ids,
            created_date__gte=timezone.now() - timedelta(days=days),
        )

    def _recent_update_count(self, post_ids: list[int], days: int) -> int:
        """Count total author updates on the given posts within the time window."""
        if not post_ids:
            return 0
        return self._recent_updates_qs(post_ids, days).count()

    def _proposals_with_updates_count(self, post_ids: list[int], days: int) -> int:
        """Count unique proposals that have at least one author update."""
        if not post_ids:
            return 0
        return (
            self._recent_updates_qs(post_ids, days)
            .values("thread__object_id")
            .distinct()
            .count()
        )


class FundingOverviewService(_AuthorUpdateMixin):
    """Service for calculating funding portfolio dashboard metrics for grant creators."""

    def get_funding_overview(self, user: User) -> dict:
        """Return funding overview metrics for a given user."""
        user_applications = GrantApplication.objects.for_user_grants(user)
        grant_fundraise_ids = user_applications.fundraise_ids()
        proposal_post_ids = list(user_applications.values_list("preregistration_post_id", flat=True).distinct())
        user_funded_ids = get_funded_fundraise_ids(user.id)
        funded_grant_proposals = list(grant_fundraise_ids & user_funded_ids)

        exchange_rate = RscExchangeRate.get_latest_exchange_rate()

        user_rsc = float(Purchase.objects.for_user(user.id).funding_contributions().for_fundraises(grant_fundraise_ids).sum())
        user_cents = UsdFundraiseContribution.objects.for_user(user.id).not_refunded().for_fundraises(grant_fundraise_ids).sum_cents()
        total_distributed = rsc_and_cents_to_usd(user_rsc, user_cents, exchange_rate)

        matched_rsc = float(Purchase.objects.funding_contributions().for_fundraises(funded_grant_proposals).exclude_user(user.id).sum())
        matched_cents = UsdFundraiseContribution.objects.not_refunded().for_fundraises(funded_grant_proposals).exclude_user(user.id).sum_cents()
        matched_funding = rsc_and_cents_to_usd(matched_rsc, matched_cents, exchange_rate)

        return {
            "total_distributed_usd": round(total_distributed, 2),
            "active_grants": self._active_grants(user),
            "total_applicants": self._count_applicants(user),
            "matched_funding_usd": round(matched_funding, 2),
            "recent_updates": self._recent_update_count(proposal_post_ids, RECENT_UPDATES_DAYS),
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


class GrantOverviewService(_AuthorUpdateMixin):
    """Service for calculating grant-specific dashboard metrics."""

    def get_grant_overview(self, user: User, grant: Grant) -> dict:
        """Return metrics for a specific grant."""
        applications = GrantApplication.objects.filter(grant=grant)
        fundraise_ids = set(
            applications.exclude(
                preregistration_post__unified_document__fundraises__id__isnull=True
            ).values_list(
                "preregistration_post__unified_document__fundraises__id", flat=True
            )
        )
        proposal_post_ids = list(
            applications.values_list("preregistration_post_id", flat=True).distinct()
        )
        user_funded_ids = get_funded_fundraise_ids(user.id)
        funded_fundraise_ids = list(fundraise_ids & user_funded_ids)

        exchange_rate = RscExchangeRate.get_latest_exchange_rate()
        fundraise_id_list = list(fundraise_ids)
        budget_used = self._get_budget_used(user, fundraise_id_list, exchange_rate)
        matched_funding = self._get_matched_funding(user, funded_fundraise_ids, exchange_rate)

        return {
            "budget_used_usd": round(budget_used, 2),
            "budget_total_usd": float(grant.amount),
            "matched_funding_usd": round(matched_funding, 2),
            "recent_updates": self._recent_update_count(proposal_post_ids, RECENT_UPDATES_DAYS),
            "proposals_with_updates": self._proposals_with_updates_count(
                proposal_post_ids, RECENT_UPDATES_DAYS
            ),
            "total_proposals": applications.count(),
            "proposals_funded": len(funded_fundraise_ids),
            "deadline": grant.end_date.isoformat() if grant.end_date else None,
        }

    def _get_budget_used(self, user: User, fundraise_ids: list[int], exchange_rate: float) -> float:
        """Calculate total amount user has contributed to grant's proposals."""
        if not fundraise_ids:
            return 0.0
        user_rsc = float(
            Purchase.objects.for_user(user.id)
            .funding_contributions()
            .for_fundraises(fundraise_ids)
            .sum()
        )
        user_cents = (
            UsdFundraiseContribution.objects.for_user(user.id)
            .not_refunded()
            .for_fundraises(fundraise_ids)
            .sum_cents()
        )
        return rsc_and_cents_to_usd(user_rsc, user_cents, exchange_rate)

    def _get_matched_funding(self, user: User, fundraise_ids: list[int], exchange_rate: float) -> float:
        """Calculate contributions from others to funded proposals."""
        if not fundraise_ids:
            return 0.0
        matched_rsc = float(
            Purchase.objects.funding_contributions()
            .for_fundraises(fundraise_ids)
            .exclude_user(user.id)
            .sum()
        )
        matched_cents = (
            UsdFundraiseContribution.objects.not_refunded()
            .for_fundraises(fundraise_ids)
            .exclude_user(user.id)
            .sum_cents()
        )
        return rsc_and_cents_to_usd(matched_rsc, matched_cents, exchange_rate)
