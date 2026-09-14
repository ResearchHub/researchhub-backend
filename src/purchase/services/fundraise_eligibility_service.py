from django.db.models import Exists, OuterRef, Q, QuerySet

from purchase.models import Fundraise, UsdFundraiseContribution


def filter_fundraises_with_funding(
    fundraises: QuerySet[Fundraise],
) -> QuerySet[Fundraise]:
    """Filter fundraises to those with non-refunded RSC or USD funding."""
    eligible_usd_contributions = UsdFundraiseContribution.objects.not_refunded().filter(
        fundraise_id=OuterRef("pk"),
        amount_cents__gt=0,
    )
    return fundraises.filter(
        Q(escrow__amount_holding__gt=0)
        | Q(escrow__amount_paid__gt=0)
        | Exists(eligible_usd_contributions)
    )
