from decimal import Decimal
from typing import Union

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType

from purchase.models import Fundraise
from purchase.related_models.constants.currency import USD
from reputation.models import Escrow
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from utils.sentry import log_error


class FundraiseValidationError(Exception):
    """Custom exception for fundraise validation errors"""

    pass


class FundraiseService:
    """
    Service for managing fundraise-related operations.
    """

    def create_fundraise_with_escrow(
        self,
        user: User,
        unified_document: ResearchhubUnifiedDocument,
        goal_amount: Union[Decimal, str, float],
        goal_currency: str = USD,
        status: str = Fundraise.OPEN,
    ) -> Fundraise:
        """
        Creates a fundraise with its associated escrow.
        """
        if unified_document.document_type != PREREGISTRATION:
            raise FundraiseValidationError("Fundraise must be for a preregistration")

        try:
            goal_amount = Decimal(goal_amount)
            if goal_amount <= 0:
                raise FundraiseValidationError("goal_amount must be greater than 0")
        except (TypeError, ValueError) as e:
            log_error(e)
            raise FundraiseValidationError("Invalid goal_amount")

        if goal_currency != USD:
            raise FundraiseValidationError("goal_currency must be USD")

        existing_fundraise = Fundraise.objects.filter(
            unified_document=unified_document
        ).first()
        if existing_fundraise:
            raise FundraiseValidationError("Fundraise already exists")

        fundraise = Fundraise.objects.create(
            created_by=user,
            unified_document=unified_document,
            goal_amount=goal_amount,
            goal_currency=goal_currency,
            status=status,
        )

        escrow = Escrow.objects.create(
            created_by=user,
            hold_type=Escrow.FUNDRAISE,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=fundraise.id,
        )
        fundraise.escrow = escrow
        fundraise.save()

        return fundraise
