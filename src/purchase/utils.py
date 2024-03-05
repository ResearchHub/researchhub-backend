import time

from reputation.distributions import create_purchase_distribution
from reputation.distributor import Distributor


def distribute_support_to_authors(paper, purchase, amount):
    registered_authors = paper.authors.all()
    total_author_count = paper.true_author_count()

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
    from reputation.models import Escrow

    Escrow.objects.create(
        created_by=purchase.user,
        amount_holding=leftover_amount,
        item=paper,
        hold_type=Escrow.AUTHOR_RSC,
    )


def flattenjson(dictionary, delim):
    flattened = {}
    for i in dictionary.keys():
        if isinstance(dictionary[i], dict):
            get = flattenjson(dictionary[i], delim)
            for j in get.keys():
                flattened[i + delim + j] = get[j]
        else:
            flattened[i] = dictionary[i]

    return flattened
