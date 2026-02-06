import time
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import DecimalField, QuerySet, Sum
from django.db.models.functions import Cast, Coalesce

from purchase.models import Fundraise, Purchase, UsdFundraiseContribution
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.distributions import create_purchase_distribution
from reputation.distributor import Distributor
from reputation.models import Escrow

DECIMAL_FIELD = DecimalField(max_digits=19, decimal_places=10)


def distribute_support_to_authors(paper, purchase, amount):
    registered_authors = paper.authors.all()
    total_author_count = registered_authors.count()

    rewarded_rsc = 0
    if total_author_count:
        rsc_per_author = amount / total_author_count
        for author in registered_authors.iterator():
            recipient = author.user
            distribution = create_purchase_distribution(recipient, rsc_per_author)
            distributor = Distributor(
                distribution, recipient, purchase, time.time(), purchase.user
            )
            distributor.distribute()
            rewarded_rsc += rsc_per_author

    store_leftover_paper_support(paper, purchase, amount - rewarded_rsc)


def store_leftover_paper_support(paper, purchase, leftover_amount):
    Escrow.objects.create(
        created_by=purchase.user,
        amount_holding=leftover_amount,
        item=paper,
        hold_type=Escrow.AUTHOR_RSC,
    )


def get_funded_fundraise_ids(user_id: int) -> set[int]:
    """Get fundraise IDs that the user has contributed to via RSC or USD."""
    rsc_funded = set(
        Purchase.objects.filter(
            user_id=user_id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            content_type=ContentType.objects.get_for_model(Fundraise),
        ).values_list("object_id", flat=True)
    )
    usd_funded = set(
        UsdFundraiseContribution.objects.filter(
            user_id=user_id,
            is_refunded=False,
        ).values_list("fundraise_id", flat=True)
    )
    return rsc_funded | usd_funded


def get_grant_fundraise_ids(user) -> set[int]:
    """Get fundraise IDs for proposals that applied to user's grants."""
    return set(
        Fundraise.objects.filter(
            unified_document__posts__grant_applications__grant__unified_document__posts__created_by=user
        ).values_list("id", flat=True)
    )


def sum_contributions(
    user_id: int | None = None,
    fundraise_ids: set[int] | list[int] | None = None,
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

    return round(RscExchangeRate.rsc_to_usd(float(rsc_total)) + usd_cents / 100, 2)
