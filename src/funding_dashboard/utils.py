from functools import lru_cache

from django.contrib.contenttypes.models import ContentType

from purchase.models import Fundraise, Purchase, UsdFundraiseContribution


@lru_cache(maxsize=1)
def get_fundraise_content_type() -> ContentType:
    return ContentType.objects.get_for_model(Fundraise)


def get_funded_fundraise_ids(user_id: int) -> list[int]:
    """Get fundraise IDs that the user has contributed to via RSC or USD."""
    rsc_funded = set(
        Purchase.objects.filter(
            user_id=user_id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            content_type=get_fundraise_content_type(),
        ).values_list("object_id", flat=True)
    )
    usd_funded = set(
        UsdFundraiseContribution.objects.filter(
            user_id=user_id,
            is_refunded=False,
        ).values_list("fundraise_id", flat=True)
    )
    return list(rsc_funded | usd_funded)
