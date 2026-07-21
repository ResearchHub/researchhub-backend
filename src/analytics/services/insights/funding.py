from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, DecimalField, F, Q, Sum
from django.db.models.functions import Cast, Coalesce

from purchase.models import (
    Balance,
    Grant,
    GrantApplication,
    Payment,
    Purchase,
    RscExchangeRate,
    UsdFundraiseContribution,
)
from purchase.related_models.payment_model import PaymentProcessor, PaymentPurpose
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import PREREGISTRATION

AMOUNT_FIELD = DecimalField(max_digits=30, decimal_places=10)


def _latest_rsc_usd_rate():
    rate = (
        RscExchangeRate.objects.order_by("-created_date")
        .values_list("rate", flat=True)
        .first()
    )
    return Decimal(str(rate)) if rate is not None else Decimal(0)


def _sum_rsc_with_usd_snapshot(
    queryset,
    amount_field="amount",
    rate_field="rsc_usd_rate",
):
    annotated = queryset.annotate(
        amount_decimal=Cast(amount_field, AMOUNT_FIELD),
        rate_decimal=Cast(rate_field, AMOUNT_FIELD),
    )
    totals = annotated.aggregate(
        rsc=Coalesce(Sum("amount_decimal"), Decimal(0)),
        usd_with_rate=Coalesce(
            Sum(
                F("amount_decimal") * F("rate_decimal"),
                filter=Q(rate_decimal__isnull=False),
                output_field=AMOUNT_FIELD,
            ),
            Decimal(0),
        ),
        rsc_without_rate=Coalesce(
            Sum("amount_decimal", filter=Q(rate_decimal__isnull=True)),
            Decimal(0),
        ),
    )
    return {
        "rsc": totals["rsc"],
        "usd_snapshot": (
            totals["usd_with_rate"]
            + totals["rsc_without_rate"] * _latest_rsc_usd_rate()
        ),
    }


def _sum_contribution_balance_method(queryset):
    total = queryset.annotate(amount_decimal=Cast("amount", AMOUNT_FIELD)).aggregate(
        rsc=Coalesce(Sum("amount_decimal"), Decimal(0)),
    )["rsc"]
    return -total


def get_funding_metrics(period):
    grants = Grant.objects.filter(
        created_date__gte=period.start,
        created_date__lt=period.end,
    )
    applications = GrantApplication.objects.filter(
        created_date__gte=period.start,
        created_date__lt=period.end,
    )
    proposals = ResearchhubPost.objects.filter(
        document_type=PREREGISTRATION,
        unified_document__is_removed=False,
        created_date__gte=period.start,
        created_date__lt=period.end,
    )
    proposal_counts = proposals.aggregate(
        total=Count("id", distinct=True),
        independent=Count(
            "id",
            filter=Q(grant_applications__isnull=True),
            distinct=True,
        ),
        public=Count(
            "id",
            filter=Q(unified_document__is_public=True),
            distinct=True,
        ),
        private=Count(
            "id",
            filter=Q(unified_document__is_public=False),
            distinct=True,
        ),
    )

    rsc_contributions = Purchase.objects.funding_contributions().filter(
        paid_status=Purchase.PAID,
        created_date__gte=period.start,
        created_date__lt=period.end,
    )
    usd_contributions = UsdFundraiseContribution.objects.not_refunded().filter(
        status=UsdFundraiseContribution.Status.SUBMITTED,
        created_date__gte=period.start,
        created_date__lt=period.end,
    )

    rsc_totals = _sum_rsc_with_usd_snapshot(rsc_contributions)
    rsc_total = rsc_totals["rsc"]
    usd_totals = usd_contributions.aggregate(
        total_cents=Coalesce(Sum("amount_cents"), 0),
        endaoment_cents=Coalesce(
            Sum("amount_cents", filter=~Q(origin_fund_id="")),
            0,
        ),
    )
    stripe_rsc_purchases = Payment.objects.filter(
        payment_processor=PaymentProcessor.STRIPE,
        purpose=PaymentPurpose.RSC_PURCHASE,
        currency__iexact="USD",
        created_date__gte=period.start,
        created_date__lt=period.end,
    ).aggregate(
        total_cents=Coalesce(Sum("amount"), 0),
    )

    purchase_content_type = ContentType.objects.get_for_model(Purchase)
    contribution_debits = Balance.objects.annotate(
        decimal_amount=Cast("amount", AMOUNT_FIELD)
    ).filter(
        purchase__in=rsc_contributions,
        content_type=purchase_content_type,
        object_id=F("purchase_id"),
        decimal_amount__lt=0,
    )
    researchcoin_balance = _sum_contribution_balance_method(
        contribution_debits.filter(is_locked=False)
    )
    funding_credits = _sum_contribution_balance_method(
        contribution_debits.filter(
            is_locked=True,
            lock_type=Balance.LockType.FUNDING_CREDIT,
        )
    )
    promotional_credits = _sum_contribution_balance_method(
        contribution_debits.filter(
            is_locked=True,
            lock_type=Balance.LockType.PROMOTIONAL,
        )
    )
    unique_funders = set(rsc_contributions.values_list("user_id", flat=True))
    unique_funders.update(usd_contributions.values_list("user_id", flat=True))

    tied_to_opportunity = (
        applications.values("preregistration_post_id").distinct().count()
    )
    return {
        "opportunities_created": grants.count(),
        "proposals": {
            "submitted": proposal_counts["total"],
            "independent": proposal_counts["independent"],
            "tied_to_opportunity": tied_to_opportunity,
            "public": proposal_counts["public"],
            "private": proposal_counts["private"],
        },
        "funded": {
            "rsc": rsc_total,
            "rsc_usd_snapshot": rsc_totals["usd_snapshot"],
            "usd": Decimal(usd_totals["total_cents"]) / 100,
            "unique_funders": len(unique_funders),
            "payment_methods": {
                "rsc": researchcoin_balance,
                "stripe": Decimal(stripe_rsc_purchases["total_cents"]) / 100,
                "daf": Decimal(usd_totals["endaoment_cents"]) / 100,
                "funding_credits": funding_credits,
                "promotional_credits": promotional_credits,
            },
        },
    }
