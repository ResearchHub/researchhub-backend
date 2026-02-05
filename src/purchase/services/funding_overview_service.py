from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Case, Count, DecimalField, IntegerField, QuerySet, Sum, When
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

from purchase.models import Fundraise, Grant, GrantApplication, Purchase
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from purchase.utils import get_funded_fundraise_ids
from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import User

RECENT_UPDATES_DAYS = 30
DECIMAL_FIELD = DecimalField(max_digits=19, decimal_places=10)


class FundingOverviewService:
    """Service for calculating funding dashboard metrics."""

    def get_funding_overview(self, user: User) -> dict:
        """Return funding overview metrics for a given user."""
        funded_ids = get_funded_fundraise_ids(user.id)
        doc_ids = self._get_doc_ids(funded_ids)
        return {
            "total_distributed_usd": self._sum_contributions(user_id=user.id),
            "active_grants": self._active_grants(user),
            "total_applicants": self._count_applicants(user),
            "matched_funding_usd": self._sum_contributions(
                fundraise_ids=funded_ids, exclude_user_id=user.id
            ),
            "recent_updates": self._update_count(doc_ids, RECENT_UPDATES_DAYS),
            "proposals_funded": len(funded_ids),
        }

    def _count_applicants(self, user: User) -> int:
        """Count unique applicants to the user's grants."""
        return (
            GrantApplication.objects.filter(grant__created_by=user)
            .values("applicant_id")
            .distinct()
            .count()
        )

    def _sum_contributions(
        self,
        user_id: int | None = None,
        fundraise_ids: list[int] | None = None,
        exclude_user_id: int | None = None,
    ) -> float:
        """Sum contributions in USD, combining RSC and USD payments."""
        if fundraise_ids is not None and not fundraise_ids:
            return 0.0

        def apply_filters(qs: QuerySet, id_field: str) -> QuerySet:
            if user_id:
                qs = qs.filter(user_id=user_id)
            if fundraise_ids:
                qs = qs.filter(**{f"{id_field}__in": fundraise_ids})
            if exclude_user_id:
                qs = qs.exclude(user_id=exclude_user_id)
            return qs

        rsc_qs = apply_filters(
            Purchase.objects.filter(
                purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                content_type=ContentType.objects.get_for_model(Fundraise),
            ),
            "object_id",
        )
        rsc_total = rsc_qs.annotate(amt=Cast("amount", DECIMAL_FIELD)).aggregate(
            total=Coalesce(Sum("amt"), Decimal("0"))
        )["total"]

        usd_qs = apply_filters(
            UsdFundraiseContribution.objects.filter(is_refunded=False),
            "fundraise_id",
        )
        usd_cents = usd_qs.aggregate(total=Coalesce(Sum("amount_cents"), 0))["total"]

        return self._combine_rsc_usd(rsc_total, usd_cents)

    def _combine_rsc_usd(self, rsc_amount: Decimal | float, usd_cents: int) -> float:
        """Convert RSC to USD and add USD cents, returning rounded total."""
        return round(RscExchangeRate.rsc_to_usd(float(rsc_amount)) + usd_cents / 100, 2)

    def _active_grants(self, user: User) -> dict:
        """Count active and total grants created by the user."""
        result = Grant.objects.filter(created_by=user).aggregate(
            total=Count("id"),
            active=Count(
                Case(When(status=Grant.OPEN, then=1), output_field=IntegerField())
            ),
        )
        return {"active": result["active"], "total": result["total"]}

    def _get_doc_ids(self, funded_ids: list[int]) -> list[int]:
        """Get unified document IDs for the given fundraise IDs."""
        if not funded_ids:
            return []
        return list(
            Fundraise.objects.filter(id__in=funded_ids).values_list(
                "unified_document_id", flat=True
            )
        )

    def _update_count(self, doc_ids: list[int], days: int) -> int:
        """Count author updates on the given documents within the time window."""
        if not doc_ids:
            return 0
        unified_doc_ct = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
        return RhCommentModel.objects.filter(
            comment_type=AUTHOR_UPDATE,
            thread__content_type=unified_doc_ct,
            thread__object_id__in=doc_ids,
            created_date__gte=timezone.now() - timedelta(days=days),
        ).count()
