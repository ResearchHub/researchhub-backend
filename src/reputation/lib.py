from reputation.models import Distribution


def get_unpaid_distributions(user):
    return user.reputation_records.filter(
        paid_status=None,
        distributed_status=Distribution.DISTRIBUTED
    )


def get_total_reputation_from_distributions(distributions):
    return sum([d.amount for d in distributions])
