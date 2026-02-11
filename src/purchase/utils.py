import time

from purchase.models import Purchase, UsdFundraiseContribution
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.distributions import create_purchase_distribution
from reputation.distributor import Distributor
from reputation.models import Escrow


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
        Purchase.objects.for_user(user_id).funding_contributions().values_list("object_id", flat=True)
    )
    usd_funded = set(
        UsdFundraiseContribution.objects.for_user(user_id).not_refunded().values_list("fundraise_id", flat=True)
    )
    return rsc_funded | usd_funded


def sum_contributions(
    user_id: int | None = None,
    fundraise_ids: set[int] | list[int] | None = None,
    exclude_user_id: int | None = None,
) -> float:
    """Sum contributions in USD, combining RSC and USD payments."""
    if fundraise_ids is not None and not fundraise_ids:
        return 0.0

    # Build RSC query with chainable methods
    rsc_qs = Purchase.objects.funding_contributions()
    if user_id:
        rsc_qs = rsc_qs.for_user(user_id)
    if fundraise_ids:
        rsc_qs = rsc_qs.for_fundraises(fundraise_ids)
    if exclude_user_id:
        rsc_qs = rsc_qs.exclude_user(exclude_user_id)

    # Build USD query with chainable methods
    usd_qs = UsdFundraiseContribution.objects.not_refunded()
    if user_id:
        usd_qs = usd_qs.for_user(user_id)
    if fundraise_ids:
        usd_qs = usd_qs.for_fundraises(fundraise_ids)
    if exclude_user_id:
        usd_qs = usd_qs.exclude_user(exclude_user_id)

    rsc_total = rsc_qs.rsc_sum()
    usd_cents = usd_qs.cents_sum()

    return round(RscExchangeRate.rsc_to_usd(float(rsc_total)) + usd_cents / 100, 2)
