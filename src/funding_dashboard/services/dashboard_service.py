from datetime import timedelta
from decimal import Decimal
from functools import cached_property
from typing import TypedDict

from django.contrib.contenttypes.models import ContentType
from django.db.models import Case, Count, DecimalField, IntegerField, Sum, When
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

from funding_dashboard.utils import get_funded_fundraise_ids, get_fundraise_content_type
from purchase.models import Fundraise, Grant, GrantApplication, Purchase, UsdFundraiseContribution
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import User

UPDATES_LOOKBACK_DAYS = 30


class ActiveRfps(TypedDict):
    active: int
    total: int


class DashboardOverview(TypedDict):
    total_distributed_usd: float
    active_rfps: ActiveRfps
    total_applicants: int
    matched_funding_usd: float
    recent_updates: int
    proposals_funded: int


class DashboardService:
    """Calculates funder dashboard metrics for a given user."""

    def __init__(self, user: User):
        self.user = user

    def get_overview(self) -> DashboardOverview:
        """Return all dashboard metrics for the user."""
        funded_fundraise_ids = get_funded_fundraise_ids(self.user.id)
        return {
            "total_distributed_usd": self._calculate_total_distributed_usd(),
            "active_rfps": self._get_active_rfps(),
            "total_applicants": self._count_applicants(),
            "matched_funding_usd": self._calculate_matched_funding_usd(
                funded_fundraise_ids
            ),
            "recent_updates": self._count_recent_updates(funded_fundraise_ids),
            "proposals_funded": len(funded_fundraise_ids),
        }

    @cached_property
    def _unified_doc_content_type(self) -> ContentType:
        return ContentType.objects.get_for_model(ResearchhubUnifiedDocument)

    def _sum_rsc_contributions_usd(
        self,
        user: User | None = None,
        fundraise_ids: list[int] | None = None,
        exclude_user: User | None = None,
    ) -> float:
        queryset = Purchase.objects.filter(
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            content_type=get_fundraise_content_type(),
        )
        if user:
            queryset = queryset.filter(user=user)
        if fundraise_ids:
            queryset = queryset.filter(object_id__in=fundraise_ids)
        if exclude_user:
            queryset = queryset.exclude(user=exclude_user)

        total_rsc = queryset.annotate(
            amount_decimal=Cast("amount", DecimalField(max_digits=19, decimal_places=10))
        ).aggregate(total=Coalesce(Sum("amount_decimal"), Decimal("0")))["total"]

        return RscExchangeRate.rsc_to_usd(float(total_rsc))

    def _sum_usd_contributions(
        self,
        user: User | None = None,
        fundraise_ids: list[int] | None = None,
        exclude_user: User | None = None,
    ) -> float:
        queryset = UsdFundraiseContribution.objects.filter(is_refunded=False)
        if user:
            queryset = queryset.filter(user=user)
        if fundraise_ids:
            queryset = queryset.filter(fundraise_id__in=fundraise_ids)
        if exclude_user:
            queryset = queryset.exclude(user=exclude_user)

        cents = queryset.aggregate(total=Coalesce(Sum("amount_cents"), 0))["total"]
        return cents / 100.0

    def _calculate_total_distributed_usd(self) -> float:
        rsc_usd = self._sum_rsc_contributions_usd(user=self.user)
        direct_usd = self._sum_usd_contributions(user=self.user)
        return round(rsc_usd + direct_usd, 2)

    def _get_active_rfps(self) -> ActiveRfps:
        result = Grant.objects.filter(created_by=self.user).aggregate(
            total=Count("id"),
            active=Count(
                Case(When(status=Grant.OPEN, then=1), output_field=IntegerField())
            ),
        )
        return {"active": result["active"], "total": result["total"]}

    def _count_applicants(self) -> int:
        return GrantApplication.objects.filter(
            grant__created_by=self.user
        ).values("applicant_id").distinct().count()

    def _calculate_matched_funding_usd(self, funded_fundraise_ids: list[int]) -> float:
        if not funded_fundraise_ids:
            return 0.0

        rsc_usd = self._sum_rsc_contributions_usd(
            fundraise_ids=funded_fundraise_ids,
            exclude_user=self.user,
        )
        direct_usd = self._sum_usd_contributions(
            fundraise_ids=funded_fundraise_ids,
            exclude_user=self.user,
        )
        return round(rsc_usd + direct_usd, 2)

    def _count_recent_updates(self, funded_fundraise_ids: list[int]) -> int:
        if not funded_fundraise_ids:
            return 0

        unified_doc_ids = Fundraise.objects.filter(
            id__in=funded_fundraise_ids
        ).values_list("unified_document_id", flat=True)

        lookback_date = timezone.now() - timedelta(days=UPDATES_LOOKBACK_DAYS)
        return RhCommentModel.objects.filter(
            comment_type=AUTHOR_UPDATE,
            thread__content_type=self._unified_doc_content_type,
            thread__object_id__in=unified_doc_ids,
            created_date__gte=lookback_date,
        ).count()
