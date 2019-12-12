from reputation.models import Distribution
from reputation.utils import get_total_reputation_from_distributions


def get_unpaid_distributions(user):
    return user.reputation_records.filter(
        paid_status=None,
        distributed_status=Distribution.DISTRIBUTED
    )


def get_user_balance(user):
    unpaid_distributions = get_unpaid_distributions(user)
    return get_total_reputation_from_distributions(unpaid_distributions)
