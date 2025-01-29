import decimal
import time

from django.contrib.contenttypes.models import ContentType
from rest_framework.response import Response

from purchase.models import Fundraise
from purchase.related_models.constants.currency import USD
from reputation.distributions import create_purchase_distribution
from reputation.distributor import Distributor
from reputation.models import Escrow
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from utils.sentry import log_error


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


def create_fundraise_with_escrow(
    user, unified_document, goal_amount, goal_currency=USD, status=Fundraise.OPEN
):
    """
    Helper function to create a fundraise with its associated escrow.
    Returns (fundraise, error_response) tuple where error_response is None if successful

    Note: This function should be called within a transaction.atomic() block
    """
    # Validate inputs
    if not unified_document.document_type == PREREGISTRATION:
        return None, Response(
            {"message": "Fundraise must be for a preregistration"}, status=400
        )

    try:
        goal_amount = decimal.Decimal(goal_amount)
        if goal_amount <= 0:
            return None, Response(
                {"message": "goal_amount must be greater than 0"}, status=400
            )
    except Exception as e:
        log_error(e)
        return None, Response({"detail": "Invalid goal_amount"}, status=400)

    if goal_currency != USD:
        return None, Response({"message": "goal_currency must be USD"}, status=400)

    # Check if fundraise already exists
    existing_fundraise = Fundraise.objects.filter(
        unified_document=unified_document
    ).first()
    if existing_fundraise:
        return None, Response({"message": "Fundraise already exists"}, status=400)

    # Create fundraise object
    fundraise = Fundraise.objects.create(
        created_by=user,
        unified_document=unified_document,
        goal_amount=goal_amount,
        goal_currency=goal_currency,
        status=status,
    )
    # Create escrow object
    escrow = Escrow.objects.create(
        created_by=user,
        hold_type=Escrow.FUNDRAISE,
        content_type=ContentType.objects.get_for_model(Fundraise),
        object_id=fundraise.id,
    )
    fundraise.escrow = escrow
    fundraise.save()

    return fundraise, None
