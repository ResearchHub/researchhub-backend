from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from functools import cached_property

from django.contrib.contenttypes.models import ContentType
from django.db.models import Case, Count, DecimalField, IntegerField, QuerySet, Sum, When
from django.db.models.functions import Cast, Coalesce, TruncMonth
from django.utils import timezone

from organizations.models import NonprofitFundraiseLink
from purchase.models import Fundraise, Grant, GrantApplication, Purchase
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from purchase.utils import get_funded_fundraise_ids, get_fundraise_content_type
from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import User

RECENT_UPDATES_DAYS = 30
UPDATE_FREQUENCY_DAYS = 180
MONTHS_TO_DISPLAY = 6
TOP_TOPICS_LIMIT = 6
MAX_UPDATE_BUCKET_THRESHOLD = 3
AMOUNT_MILESTONES = [1000, 5000, 10000, 25000, 50000, 100000]
RESEARCHER_MILESTONES = [1, 5, 10, 25, 50, 100]
UPDATE_BUCKETS = ["0", "1", "2-3", "4+"]
DECIMAL_FIELD = DecimalField(max_digits=19, decimal_places=10)


@dataclass
class FundingContext:
    """Holds computed data for building funding overview response."""

    user: User
    funded_ids: list[int]
    doc_ids: list[int]
    contrib_map: dict[int, float]
    total_usd: float
    matched_usd: float
    researchers: int
    applicants: int


class FundingOverviewService:
    """Service for calculating funding dashboard metrics."""

    @cached_property
    def _unified_doc_ct(self) -> ContentType:
        return ContentType.objects.get_for_model(ResearchhubUnifiedDocument)

    def get_funding_overview(self, user: User) -> dict:
        """Return funding overview metrics for a given user."""
        funded_ids = get_funded_fundraise_ids(user.id)
        ctx = FundingContext(
            user=user,
            funded_ids=funded_ids,
            doc_ids=self._get_doc_ids(funded_ids),
            contrib_map=self._contributions_by_fundraise(user, funded_ids),
            total_usd=self._sum_contributions(user_id=user.id),
            matched_usd=self._sum_contributions(fundraise_ids=funded_ids, exclude_user_id=user.id),
            researchers=self._count_researchers(funded_ids),
            applicants=self._count_applicants(user),
        )
        return self._build_response(ctx)

    def _build_response(self, ctx: FundingContext) -> dict:
        """Build the top-level funding overview response structure."""
        return {
            "total_distributed_usd": ctx.total_usd,
            "active_grants": self._active_grants(ctx.user),
            "total_applicants": ctx.applicants,
            "matched_funding_usd": ctx.matched_usd,
            "recent_updates": self._update_count(ctx.doc_ids, RECENT_UPDATES_DAYS),
            "proposals_funded": len(ctx.funded_ids),
            "impact": self._build_impact(ctx),
        }

    def _build_impact(self, ctx: FundingContext) -> dict:
        """Build the nested impact metrics section."""
        return {
            "milestones": {
                "funding_contributed": self._milestone(ctx.total_usd, AMOUNT_MILESTONES),
                "researchers_supported": self._milestone(ctx.researchers, RESEARCHER_MILESTONES),
                "matched_funding": self._milestone(ctx.matched_usd, AMOUNT_MILESTONES),
            },
            "funding_over_time": self._funding_over_time(ctx.user, ctx.funded_ids),
            "topic_breakdown": self._topic_breakdown(ctx.funded_ids, ctx.contrib_map),
            "update_frequency": self._update_frequency(ctx.doc_ids),
            "institutions_supported": self._institutions(ctx.funded_ids, ctx.contrib_map),
        }

    def _count_researchers(self, funded_ids: list[int]) -> int:
        """Count unique researchers whose proposals the user has funded."""
        if not funded_ids:
            return 0
        return Fundraise.objects.filter(id__in=funded_ids).values("created_by_id").distinct().count()

    def _count_applicants(self, user: User) -> int:
        """Count unique applicants to the user's grants."""
        return GrantApplication.objects.filter(grant__created_by=user).values("applicant_id").distinct().count()

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
                content_type=get_fundraise_content_type(),
            ),
            "object_id",
        )
        rsc_total = rsc_qs.annotate(
            amt=Cast("amount", DECIMAL_FIELD)
        ).aggregate(t=Coalesce(Sum("amt"), Decimal("0")))["t"]

        usd_qs = apply_filters(
            UsdFundraiseContribution.objects.filter(is_refunded=False),
            "fundraise_id",
        )
        usd_cents = usd_qs.aggregate(t=Coalesce(Sum("amount_cents"), 0))["t"]

        return self._combine_rsc_usd(rsc_total, usd_cents)

    def _contributions_by_fundraise(self, user: User, funded_ids: list[int]) -> dict[int, float]:
        """Map each fundraise ID to the user's contribution in USD."""
        if not funded_ids:
            return {}

        rsc = {
            r["object_id"]: r["t"] or Decimal("0")
            for r in Purchase.objects.filter(
                user=user,
                purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                content_type=get_fundraise_content_type(),
                object_id__in=funded_ids,
            ).values("object_id").annotate(t=Sum(Cast("amount", DECIMAL_FIELD)))
        }
        usd = {
            r["fundraise_id"]: r["t"] or 0
            for r in UsdFundraiseContribution.objects.filter(
                user=user, fundraise_id__in=funded_ids, is_refunded=False
            ).values("fundraise_id").annotate(t=Sum("amount_cents"))
        }
        return {
            fid: self._combine_rsc_usd(rsc.get(fid, 0), usd.get(fid, 0))
            for fid in funded_ids
        }

    def _combine_rsc_usd(self, rsc_amount: Decimal | float, usd_cents: int) -> float:
        """Convert RSC to USD and add USD cents, returning rounded total."""
        return round(RscExchangeRate.rsc_to_usd(float(rsc_amount)) + usd_cents / 100, 2)

    def _milestone(self, current: float, tiers: list[int]) -> dict:
        """Return current value and next milestone target."""
        target = next((t for t in tiers if current < t), tiers[-1])
        return {"current": float(current), "target": float(target)}

    def _active_grants(self, user: User) -> dict:
        """Count active and total grants created by the user."""
        result = Grant.objects.filter(created_by=user).aggregate(
            total=Count("id"),
            active=Count(Case(When(status=Grant.OPEN, then=1), output_field=IntegerField())),
        )
        return {"active": result["active"], "total": result["total"]}

    def _get_doc_ids(self, funded_ids: list[int]) -> list[int]:
        """Get unified document IDs for the given fundraise IDs."""
        if not funded_ids:
            return []
        return list(
            Fundraise.objects.filter(id__in=funded_ids)
            .values_list("unified_document_id", flat=True)
        )

    def _update_count(self, doc_ids: list[int], days: int) -> int:
        """Count author updates on the given documents within the time window."""
        if not doc_ids:
            return 0
        return RhCommentModel.objects.filter(
            comment_type=AUTHOR_UPDATE,
            thread__content_type=self._unified_doc_ct,
            thread__object_id__in=doc_ids,
            created_date__gte=timezone.now() - timedelta(days=days),
        ).count()

    def _funding_over_time(self, user: User, funded_ids: list[int]) -> list[dict]:
        """Return 6 months of funding data (user vs matched contributions)."""
        now = timezone.now()
        months = [
            f"{now.year + (now.month - 1 - i) // 12}-{(now.month - 1 - i) % 12 + 1:02d}"
            for i in range(MONTHS_TO_DISPLAY - 1, -1, -1)
        ]

        if not funded_ids:
            return [{"month": m, "user_contributions": 0.0, "matched_contributions": 0.0} for m in months]

        rsc = self._monthly_totals(
            Purchase.objects.filter(
                purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                content_type=get_fundraise_content_type(),
                object_id__in=funded_ids,
            ),
            user, "amount", is_decimal=True,
        )
        usd = self._monthly_totals(
            UsdFundraiseContribution.objects.filter(fundraise_id__in=funded_ids, is_refunded=False),
            user, "amount_cents", is_decimal=False,
        )

        result = []
        for m in months:
            rsc_data, usd_data = rsc.get(m, {}), usd.get(m, {})
            result.append({
                "month": m,
                "user_contributions": self._combine_rsc_usd(rsc_data.get("user", 0), usd_data.get("user", 0)),
                "matched_contributions": self._combine_rsc_usd(rsc_data.get("matched", 0), usd_data.get("matched", 0)),
            })
        return result

    def _monthly_totals(self, qs: QuerySet, user: User, field: str, is_decimal: bool) -> dict:
        """Aggregate contributions by month, split into user vs matched."""
        agg = Sum(Cast(field, DECIMAL_FIELD)) if is_decimal else Sum(field)
        zero = Decimal("0") if is_decimal else 0
        result: dict = defaultdict(lambda: {"user": zero, "matched": zero})
        for row in qs.annotate(month=TruncMonth("created_date")).values("month", "user_id").annotate(t=agg):
            key = "user" if row["user_id"] == user.id else "matched"
            result[row["month"].strftime("%Y-%m")][key] += row["t"] or zero
        return dict(result)

    def _topic_breakdown(self, funded_ids: list[int], contrib_map: dict[int, float]) -> list[dict]:
        """Return top topics by funding amount from the user's contributions."""
        if not funded_ids:
            return []
        totals: dict[str, float] = defaultdict(float)
        for f in Fundraise.objects.filter(id__in=funded_ids).prefetch_related("unified_document__hubs"):
            for hub in f.unified_document.hubs.all():
                totals[hub.name] += contrib_map.get(f.id, 0.0)
        sorted_topics = sorted(totals.items(), key=lambda x: -x[1])[:TOP_TOPICS_LIMIT]
        return [{"name": n, "amount_usd": round(a, 2)} for n, a in sorted_topics]

    def _update_frequency(self, doc_ids: list[int]) -> list[dict]:
        """Bucket proposals by how many updates they've posted."""
        if not doc_ids:
            return [{"bucket": b, "count": 0} for b in UPDATE_BUCKETS]

        counts = dict(
            RhCommentModel.objects.filter(
                comment_type=AUTHOR_UPDATE,
                thread__content_type=self._unified_doc_ct,
                thread__object_id__in=doc_ids,
                created_date__gte=timezone.now() - timedelta(days=UPDATE_FREQUENCY_DAYS),
            ).values("thread__object_id").annotate(c=Count("id")).values_list("thread__object_id", "c")
        )
        buckets = Counter({b: 0 for b in UPDATE_BUCKETS})
        for doc_id in doc_ids:
            c = counts.get(doc_id, 0)
            bucket = self._get_update_bucket(c)
            buckets[bucket] += 1
        return [{"bucket": b, "count": buckets[b]} for b in UPDATE_BUCKETS]

    def _get_update_bucket(self, count: int) -> str:
        """Map update count to bucket label."""
        if count == 0:
            return "0"
        if count == 1:
            return "1"
        if count <= MAX_UPDATE_BUCKET_THRESHOLD:
            return "2-3"
        return "4+"

    def _institutions(self, funded_ids: list[int], contrib_map: dict[int, float]) -> list[dict]:
        """Return nonprofits linked to funded proposals, sorted by amount."""
        if not funded_ids:
            return []
        data: dict[int, dict] = {}
        for link in NonprofitFundraiseLink.objects.filter(fundraise_id__in=funded_ids).select_related("nonprofit"):
            nonprofit = link.nonprofit
            if nonprofit.id not in data:
                data[nonprofit.id] = {
                    "name": nonprofit.name,
                    "ein": nonprofit.ein or "",
                    "amount_usd": 0.0,
                    "project_count": 0,
                }
            data[nonprofit.id]["amount_usd"] += contrib_map.get(link.fundraise_id, 0.0)
            data[nonprofit.id]["project_count"] += 1
        return sorted(
            [{**d, "amount_usd": round(d["amount_usd"], 2)} for d in data.values()],
            key=lambda x: -x["amount_usd"],
        )
