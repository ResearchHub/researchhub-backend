from decimal import Decimal
from unittest import TestCase
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType

from purchase.models import Fundraise
from purchase.related_models.constants.currency import USD
from purchase.services.fundraise_service import (
    FundraiseService,
    FundraiseValidationError,
)
from reputation.models import Escrow
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)


class FundraiseServiceTest(TestCase):
    def setUp(self):
        self.service = FundraiseService()
        self.user = Mock(spec=User)
        self.unified_document = Mock(spec=ResearchhubUnifiedDocument)
        self.unified_document.document_type = PREREGISTRATION

    def test_create_fundraise_with_escrow_success(self):
        # Arrange
        goal_amount = Decimal("100.00")

        with patch.object(Fundraise.objects, "filter") as mock_filter, patch.object(
            Fundraise.objects, "create"
        ) as mock_create_fundraise, patch.object(
            Escrow.objects, "create"
        ) as mock_create_escrow, patch.object(
            ContentType.objects, "get_for_model"
        ) as mock_get_content_type:

            # Setup mocks
            mock_filter.return_value.first.return_value = None
            mock_fundraise = Mock(spec=Fundraise)
            mock_fundraise.id = 1
            mock_create_fundraise.return_value = mock_fundraise
            mock_escrow = Mock(spec=Escrow)
            mock_create_escrow.return_value = mock_escrow
            mock_get_content_type.return_value = Mock(spec=ContentType)

            # Act
            result = self.service.create_fundraise_with_escrow(
                self.user, self.unified_document, goal_amount, USD, Fundraise.OPEN
            )

            # Assert
            mock_create_fundraise.assert_called_once_with(
                created_by=self.user,
                unified_document=self.unified_document,
                goal_amount=goal_amount,
                goal_currency=USD,
                status=Fundraise.OPEN,
            )

            mock_create_escrow.assert_called_once()
            self.assertEqual(result, mock_fundraise)

    def test_create_fundraise_invalid_document_type(self):
        # Arrange
        self.unified_document.document_type = "NOT_PREREGISTRATION"

        # Act & Assert
        with self.assertRaises(FundraiseValidationError) as context:
            self.service.create_fundraise_with_escrow(
                self.user, self.unified_document, "100.00"
            )

        self.assertEqual(
            str(context.exception), "Fundraise must be for a preregistration"
        )

    def test_create_fundraise_invalid_goal_amount(self):
        # Act & Assert
        with self.assertRaises(FundraiseValidationError) as context:
            self.service.create_fundraise_with_escrow(
                self.user,
                self.unified_document,
                "100.00abc",
            )

        self.assertEqual(str(context.exception), "Invalid goal_amount")

    def test_create_fundraise_negative_goal_amount(self):
        # Act & Assert
        with self.assertRaises(FundraiseValidationError) as context:
            self.service.create_fundraise_with_escrow(
                self.user, self.unified_document, "-100.00"
            )

        self.assertEqual(str(context.exception), "goal_amount must be greater than 0")

    def test_create_fundraise_invalid_currency(self):
        # Act & Assert
        with self.assertRaises(FundraiseValidationError) as context:
            self.service.create_fundraise_with_escrow(
                self.user, self.unified_document, "100.00", "RSC"
            )

        self.assertEqual(str(context.exception), "goal_currency must be USD")

    def test_create_fundraise_already_exists(self):
        # Arrange
        with patch.object(Fundraise.objects, "filter") as mock_filter:
            mock_filter.return_value.first.return_value = Mock(spec=Fundraise)

            # Act & Assert
            with self.assertRaises(FundraiseValidationError) as context:
                self.service.create_fundraise_with_escrow(
                    self.user, self.unified_document, "100.00"
                )

            self.assertEqual(str(context.exception), "Fundraise already exists")
