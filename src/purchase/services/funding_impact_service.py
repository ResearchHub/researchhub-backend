from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, DecimalField, QuerySet, Sum
from django.db.models.functions import Cast, Coalesce, TruncMonth
from django.utils import timezone

from purchase.models import Fundraise, GrantApplication, Purchase
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.usd_fundraise_contribution_model import UsdFundraiseContribution
from purchase.utils import get_funded_fundraise_ids, sum_contributions
from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubPost
from user.models import User

MONTHS_TO_SHOW = 6
UPDATE_FREQUENCY_DAYS = 180
MAX_TOPICS = 5
MAX_INSTITUTIONS = 10
DECIMAL_FIELD = DecimalField(max_digits=19, decimal_places=10)

MILESTONES = {
    "funding_contributed": [100, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000],
    "researchers_supported": [1, 3, 5, 10, 25, 50, 100],
    "matched_funding": [500, 2500, 5000, 10000, 25000, 50000, 100000, 250000],
}

UPDATE_BUCKETS = ["0", "1", "2-3", "4+"]


class FundingImpactService:
    """Calculates funding impact metrics for grant creators who also contribute."""

    def get_funding_impact_overview(self, user: User) -> dict:
        """Return funding impact metrics for proposals the user funded through their grants."""
        grant_fundraise_ids = GrantApplication.objects.for_user_grants(user).fundraise_ids()
        user_funded_ids = get_funded_fundraise_ids(user.id)
        funded_ids = list(grant_fundraise_ids & user_funded_ids)

        if not funded_ids:
            return self._empty_response()

        fundraises = (
            Fundraise.objects.filter(id__in=funded_ids)
            .select_related("unified_document", "created_by__author_profile")
            .prefetch_related("created_by__author_profile__institutions__institution")
        )

        post_ids = list(
            fundraises.values_list("unified_document__posts__id", flat=True).distinct()
        )

        exchange_rate = RscExchangeRate.get_latest_exchange_rate()
        contributions = self._get_contributions_by_fundraise(user, funded_ids, exchange_rate)

        return {
            "milestones": self._get_milestones(user, funded_ids, fundraises),
            "funding_over_time": self._get_funding_over_time(user, funded_ids, exchange_rate),
            "topic_breakdown": self._get_topic_breakdown(fundraises, contributions),
            "update_frequency": self._get_update_frequency(post_ids),
            "institutions_supported": self._get_institutions_supported(fundraises, contributions),
        }

    def _empty_response(self) -> dict:
        past_months = self._get_past_months()
        return {
            "milestones": {
                key: {"current": 0, "target": vals[0]}
                for key, vals in MILESTONES.items()
            },
            "funding_over_time": [
                {"month": m, "user_contributions": 0.0, "matched_contributions": 0.0}
                for m in past_months
            ],
            "topic_breakdown": [],
            "update_frequency": [{"bucket": b, "count": 0} for b in UPDATE_BUCKETS],
            "institutions_supported": [],
        }

    def _get_past_months(self) -> list[str]:
        """Return YYYY-MM strings for the past N months, oldest first."""
        now = timezone.now()
        return [
            (now.replace(day=1) - timedelta(days=30 * i)).strftime("%Y-%m")
            for i in range(MONTHS_TO_SHOW - 1, -1, -1)
        ]

    def _get_milestone(self, current: float, key: str) -> dict:
        """Return current value and next target for a milestone."""
        targets = MILESTONES[key]
        target = next((t for t in targets if t > current), targets[-1])
        return {"current": current, "target": target}

    def _get_milestones(self, user: User, funded_ids: list[int], fundraises: QuerySet) -> dict:
        """Calculate all milestone metrics."""
        user_total = sum_contributions(user_id=user.id, fundraise_ids=funded_ids)
        matched_total = sum_contributions(fundraise_ids=funded_ids, exclude_user_id=user.id)
        researcher_count = fundraises.values("created_by_id").distinct().count()

        return {
            "funding_contributed": self._get_milestone(user_total, "funding_contributed"),
            "researchers_supported": self._get_milestone(researcher_count, "researchers_supported"),
            "matched_funding": self._get_milestone(matched_total, "matched_funding"),
        }

    def _get_contributions_by_fundraise(
        self, user: User, fundraise_ids: list[int], exchange_rate: float
    ) -> dict[int, float]:
        """Return user's contribution amount (USD) per fundraise ID."""
        rsc_amounts = dict(
            Purchase.objects.for_user(user.id).funding_contributions().for_fundraises(fundraise_ids)
            .annotate(amount_decimal=Cast("amount", DECIMAL_FIELD))
            .values("object_id")
            .annotate(total=Coalesce(Sum("amount_decimal"), Decimal("0")))
            .values_list("object_id", "total")
        )

        usd_amounts = dict(
            UsdFundraiseContribution.objects.for_user(user.id).not_refunded().for_fundraises(fundraise_ids)
            .values("fundraise_id")
            .annotate(total=Coalesce(Sum("amount_cents"), 0))
            .values_list("fundraise_id", "total")
        )

        return {
            fid: float(rsc_amounts.get(fid) or 0) * exchange_rate + (usd_amounts.get(fid) or 0) / 100
            for fid in fundraise_ids
        }

    def _get_funding_over_time(
        self, user: User, fundraise_ids: list[int], exchange_rate: float
    ) -> list[dict]:
        """Return past 6 months of cumulative funding contributions."""
        past_months = self._get_past_months()
        cutoff = timezone.now() - timedelta(days=MONTHS_TO_SHOW * 30)

        rsc_monthly = (
            Purchase.objects.funding_contributions().for_fundraises(fundraise_ids)
            .filter(created_date__gte=cutoff)
            .annotate(month=TruncMonth("created_date"), amount_decimal=Cast("amount", DECIMAL_FIELD))
            .values("month", "user_id")
            .annotate(total=Coalesce(Sum("amount_decimal"), Decimal("0")))
        )

        usd_monthly = (
            UsdFundraiseContribution.objects.not_refunded().for_fundraises(fundraise_ids)
            .filter(created_date__gte=cutoff)
            .annotate(month=TruncMonth("created_date"))
            .values("month", "user_id")
            .annotate(total=Coalesce(Sum("amount_cents"), 0))
        )

        monthly = {m: {"user": 0.0, "matched": 0.0} for m in past_months}

        for row in rsc_monthly:
            month_str = row["month"].strftime("%Y-%m")
            if month_str in monthly:
                contributor_type = "user" if row["user_id"] == user.id else "matched"
                monthly[month_str][contributor_type] += float(row["total"]) * exchange_rate

        for row in usd_monthly:
            month_str = row["month"].strftime("%Y-%m")
            if month_str in monthly:
                contributor_type = "user" if row["user_id"] == user.id else "matched"
                monthly[month_str][contributor_type] += row["total"] / 100

        cumulative_user, cumulative_matched = 0.0, 0.0
        results = []
        for month in past_months:
            cumulative_user += monthly[month]["user"]
            cumulative_matched += monthly[month]["matched"]
            results.append({
                "month": month,
                "user_contributions": round(cumulative_user, 2),
                "matched_contributions": round(cumulative_matched, 2),
            })
        return results

    def _get_topic_breakdown(self, fundraises: QuerySet, contributions: dict[int, float]) -> list[dict]:
        """Return top funded topics/hubs."""
        hub_totals: dict[str, float] = defaultdict(float)
        for fundraise in fundraises:
            hub = fundraise.unified_document.get_primary_hub(fallback=True)
            hub_totals[hub.name if hub else "Other"] += contributions.get(fundraise.id, 0)

        top_hubs = sorted(hub_totals.items(), key=lambda x: x[1], reverse=True)[:MAX_TOPICS]
        return [{"name": name, "amount_usd": round(amount, 2)} for name, amount in top_hubs]

    def _get_update_frequency(self, post_ids: list[int]) -> list[dict]:
        """Return distribution of author update counts per proposal."""
        buckets = dict.fromkeys(UPDATE_BUCKETS, 0)
        if not post_ids:
            return [{"bucket": b, "count": c} for b, c in buckets.items()]

        post_ct = ContentType.objects.get_for_model(ResearchhubPost)
        cutoff = timezone.now() - timedelta(days=UPDATE_FREQUENCY_DAYS)

        update_counts = dict(
            RhCommentModel.objects.filter(
                comment_type=AUTHOR_UPDATE,
                thread__content_type=post_ct,
                thread__object_id__in=post_ids,
                created_date__gte=cutoff,
            )
            .values("thread__object_id")
            .annotate(count=Count("id"))
            .values_list("thread__object_id", "count")
        )

        for post_id in post_ids:
            count = update_counts.get(post_id, 0)
            if count == 0:
                bucket_key = "0"
            elif count == 1:
                bucket_key = "1"
            elif count <= 3:
                bucket_key = "2-3"
            else:
                bucket_key = "4+"
            buckets[bucket_key] += 1

        return [{"bucket": b, "count": c} for b, c in buckets.items()]

    def _get_institutions_supported(
        self, fundraises: QuerySet, contributions: dict[int, float]
    ) -> list[dict]:
        """Return institutions receiving funding through user contributions."""
        institution_data: dict = defaultdict(lambda: {"amount": 0.0, "projects": set()})

        for fundraise in fundraises:
            amount = contributions.get(fundraise.id, 0)
            if not amount:
                continue

            author_profile = getattr(fundraise.created_by, "author_profile", None)
            if not author_profile:
                continue

            author_institutions = list(author_profile.institutions.all())
            if not author_institutions:
                continue

            share = amount / len(author_institutions)
            for author_inst in author_institutions:
                inst = author_inst.institution
                institution_data[inst.id]["institution"] = inst
                institution_data[inst.id]["amount"] += share
                institution_data[inst.id]["projects"].add(fundraise.id)

        results = []
        for data in institution_data.values():
            inst = data["institution"]
            location = ", ".join(filter(None, [inst.region, inst.country_code]))
            results.append({
                "name": inst.display_name,
                "ein": "",
                "location": location,
                "amount_usd": round(data["amount"], 2),
                "project_count": len(data["projects"]),
            })

        return sorted(results, key=lambda x: x["amount_usd"], reverse=True)[:MAX_INSTITUTIONS]
