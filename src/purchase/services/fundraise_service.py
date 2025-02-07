from decimal import Decimal

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType

from purchase.models import Fundraise
from purchase.related_models.constants.currency import USD
from reputation.models import Escrow
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)


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
        goal_amount: Decimal,
        goal_currency: str = USD,
        status: str = Fundraise.OPEN,
    ) -> Fundraise:
        """
        Creates a fundraise with its associated escrow.
        All input validation is handled by FundraiseCreateSerializer.
        """
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
