from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal
from functools import cached_property

from django.contrib.contenttypes.models import ContentType
from django.db.models import Case, Count, DecimalField, IntegerField, Sum, When
from django.db.models.functions import Cast, Coalesce, TruncMonth
from django.utils import timezone

from funding_dashboard.utils import get_funded_fundraise_ids, get_fundraise_content_type
from organizations.models import NonprofitFundraiseLink
from purchase.models import Fundraise, Grant, GrantApplication, Purchase, UsdFundraiseContribution
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import User

RECENT_UPDATES_DAYS = 30
UPDATE_FREQUENCY_DAYS = 180
MONTHS_TO_DISPLAY = 6
TOP_TOPICS_LIMIT = 6
AMOUNT_MILESTONES = [1000, 5000, 10000, 25000, 50000, 100000]
RESEARCHER_MILESTONES = [1, 5, 10, 25, 50, 100]
UPDATE_BUCKETS = ["0", "1", "2-3", "4+"]
DECIMAL = DecimalField(max_digits=19, decimal_places=10)


class DashboardService:
    """Calculates funder dashboard metrics for a given user."""

    def __init__(self, user: User):
        self.user = user

    def get_overview(self) -> dict:
        funded_ids = get_funded_fundraise_ids(self.user.id)
        total = self._get_contributions_usd(user_id=self.user.id)
        matched = self._get_contributions_usd(fundraise_ids=funded_ids, exclude_user_id=self.user.id)
        contrib_map = self._get_contributions_by_fundraise(funded_ids)
        doc_ids = list(Fundraise.objects.filter(id__in=funded_ids).values_list("unified_document_id", flat=True)) if funded_ids else []

        researchers = Fundraise.objects.filter(id__in=funded_ids).values("created_by_id").distinct().count() if funded_ids else 0
        applicants = GrantApplication.objects.filter(grant__created_by=self.user).values("applicant_id").distinct().count()

        return {
            "total_distributed_usd": total,
            "active_rfps": self._get_active_rfps(),
            "total_applicants": applicants,
            "matched_funding_usd": matched,
            "recent_updates": self._get_update_count(doc_ids, RECENT_UPDATES_DAYS),
            "proposals_funded": len(funded_ids),
            "impact": {
                "milestones": {
                    "funding_contributed": self._milestone(total, AMOUNT_MILESTONES),
                    "researchers_supported": self._milestone(researchers, RESEARCHER_MILESTONES),
                    "matched_funding": self._milestone(matched, AMOUNT_MILESTONES),
                },
                "funding_over_time": self._get_funding_over_time(funded_ids),
                "topic_breakdown": self._get_topic_breakdown(funded_ids, contrib_map),
                "update_frequency": self._get_update_frequency(doc_ids),
                "institutions_supported": self._get_institutions(funded_ids, contrib_map),
            },
        }

    @cached_property
    def _unified_doc_ct(self) -> ContentType:
        return ContentType.objects.get_for_model(ResearchhubUnifiedDocument)

    def _milestone(self, current: float, tiers: list[int]) -> dict:
        target = next((t for t in tiers if current < t), tiers[-1])
        return {"current": float(current), "target": float(target)}

    def _get_contributions_usd(
        self,
        user_id: int | None = None,
        fundraise_ids: list[int] | None = None,
        exclude_user_id: int | None = None,
    ) -> float:
        if fundraise_ids is not None and not fundraise_ids:
            return 0.0

        def apply_filters(qs, id_field):
            if user_id:
                qs = qs.filter(user_id=user_id)
            if fundraise_ids:
                qs = qs.filter(**{f"{id_field}__in": fundraise_ids})
            if exclude_user_id:
                qs = qs.exclude(user_id=exclude_user_id)
            return qs

        rsc_qs = apply_filters(
            Purchase.objects.filter(purchase_type=Purchase.FUNDRAISE_CONTRIBUTION, content_type=get_fundraise_content_type()),
            "object_id",
        )
        rsc = rsc_qs.annotate(a=Cast("amount", DECIMAL)).aggregate(t=Coalesce(Sum("a"), Decimal("0")))["t"]

        usd_qs = apply_filters(UsdFundraiseContribution.objects.filter(is_refunded=False), "fundraise_id")
        usd = usd_qs.aggregate(t=Coalesce(Sum("amount_cents"), 0))["t"]

        return round(RscExchangeRate.rsc_to_usd(float(rsc)) + usd / 100, 2)

    def _get_active_rfps(self) -> dict:
        r = Grant.objects.filter(created_by=self.user).aggregate(
            total=Count("id"),
            active=Count(Case(When(status=Grant.OPEN, then=1), output_field=IntegerField())),
        )
        return {"active": r["active"], "total": r["total"]}

    def _get_update_count(self, doc_ids: list[int], days: int) -> int:
        if not doc_ids:
            return 0
        return RhCommentModel.objects.filter(
            comment_type=AUTHOR_UPDATE,
            thread__content_type=self._unified_doc_ct,
            thread__object_id__in=doc_ids,
            created_date__gte=timezone.now() - timedelta(days=days),
        ).count()

    def _get_contributions_by_fundraise(self, funded_ids: list[int]) -> dict[int, float]:
        if not funded_ids:
            return {}

        rsc = {
            r["object_id"]: r["t"] or Decimal("0")
            for r in Purchase.objects.filter(
                user=self.user,
                purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                content_type=get_fundraise_content_type(),
                object_id__in=funded_ids,
            ).values("object_id").annotate(t=Sum(Cast("amount", DECIMAL)))
        }
        usd = {
            r["fundraise_id"]: r["t"] or 0
            for r in UsdFundraiseContribution.objects.filter(
                user=self.user, fundraise_id__in=funded_ids, is_refunded=False
            ).values("fundraise_id").annotate(t=Sum("amount_cents"))
        }
        return {fid: RscExchangeRate.rsc_to_usd(float(rsc.get(fid, 0))) + usd.get(fid, 0) / 100 for fid in funded_ids}

    def _get_funding_over_time(self, funded_ids: list[int]) -> list[dict]:
        now = timezone.now()
        months = [f"{now.year + (now.month - 1 - i) // 12}-{(now.month - 1 - i) % 12 + 1:02d}" for i in range(MONTHS_TO_DISPLAY - 1, -1, -1)]

        if not funded_ids:
            return [{"month": m, "user_contributions": 0.0, "matched_contributions": 0.0} for m in months]

        rsc = self._aggregate_monthly(
            Purchase.objects.filter(purchase_type=Purchase.FUNDRAISE_CONTRIBUTION, content_type=get_fundraise_content_type(), object_id__in=funded_ids),
            "amount", is_decimal=True,
        )
        usd = self._aggregate_monthly(
            UsdFundraiseContribution.objects.filter(fundraise_id__in=funded_ids, is_refunded=False),
            "amount_cents", is_decimal=False,
        )

        result = []
        for m in months:
            user_total = RscExchangeRate.rsc_to_usd(float(rsc.get(m, {}).get("user", 0))) + usd.get(m, {}).get("user", 0) / 100
            matched_total = RscExchangeRate.rsc_to_usd(float(rsc.get(m, {}).get("matched", 0))) + usd.get(m, {}).get("matched", 0) / 100
            result.append({"month": m, "user_contributions": round(user_total, 2), "matched_contributions": round(matched_total, 2)})
        return result

    def _aggregate_monthly(self, qs, field: str, is_decimal: bool) -> dict:
        agg = Sum(Cast(field, DECIMAL)) if is_decimal else Sum(field)
        zero = Decimal("0") if is_decimal else 0
        result: dict = defaultdict(lambda: {"user": zero, "matched": zero})
        for row in qs.annotate(month=TruncMonth("created_date")).values("month", "user_id").annotate(t=agg):
            result[row["month"].strftime("%Y-%m")]["user" if row["user_id"] == self.user.id else "matched"] += row["t"] or zero
        return dict(result)

    def _get_topic_breakdown(self, funded_ids: list[int], contrib_map: dict[int, float]) -> list[dict]:
        if not funded_ids:
            return []
        totals: dict[str, float] = defaultdict(float)
        for f in Fundraise.objects.filter(id__in=funded_ids).prefetch_related("unified_document__hubs"):
            for hub in f.unified_document.hubs.all():
                totals[hub.name] += contrib_map.get(f.id, 0.0)
        return [{"name": n, "amount_usd": round(a, 2)} for n, a in sorted(totals.items(), key=lambda x: -x[1])[:TOP_TOPICS_LIMIT]]

    def _get_update_frequency(self, doc_ids: list[int]) -> list[dict]:
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
            buckets["0" if c == 0 else "1" if c == 1 else "2-3" if c <= 3 else "4+"] += 1
        return [{"bucket": b, "count": buckets[b]} for b in UPDATE_BUCKETS]

    def _get_institutions(self, funded_ids: list[int], contrib_map: dict[int, float]) -> list[dict]:
        if not funded_ids:
            return []
        data: dict[int, dict] = {}
        for link in NonprofitFundraiseLink.objects.filter(fundraise_id__in=funded_ids).select_related("nonprofit"):
            np = link.nonprofit
            if np.id not in data:
                data[np.id] = {"name": np.name, "ein": np.ein, "amount_usd": 0.0, "project_count": 0}
            data[np.id]["amount_usd"] += contrib_map.get(link.fundraise_id, 0.0)
            data[np.id]["project_count"] += 1
        return sorted([{**d, "amount_usd": round(d["amount_usd"], 2)} for d in data.values()], key=lambda x: -x["amount_usd"])
