from decimal import Decimal
from unittest.mock import Mock

from rest_framework.test import APITestCase

from purchase.models import Fundraise
from purchase.related_models.constants.currency import USD
from purchase.serializers.fundraise_create_serializer import FundraiseCreateSerializer
from purchase.services.fundraise_service import FundraiseService
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_authenticated_user


class TestFundraiseService(APITestCase):
    def setUp(self):
        self.service = FundraiseService()
        self.user = create_random_authenticated_user("fundraise_test")
        self.unified_document = Mock(spec=ResearchhubUnifiedDocument)
        self.unified_document.document_type = PREREGISTRATION

    def test_create_fundraise_with_escrow_success(self):
        # Arrange
        goal_amount = Decimal("100.00")
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )

        # Act
        fundraise = self.service.create_fundraise_with_escrow(
            self.user, unified_document, goal_amount, USD, Fundraise.OPEN
        )

        # Assert
        db_fundraise = Fundraise.objects.filter(id=fundraise.id).first()
        self.assertIsNotNone(db_fundraise)
        self.assertEqual(db_fundraise.created_by, self.user)
        self.assertEqual(db_fundraise.unified_document, unified_document)
        self.assertEqual(db_fundraise.goal_amount, goal_amount)
        self.assertEqual(db_fundraise.goal_currency, USD)
        self.assertEqual(db_fundraise.status, Fundraise.OPEN)

        # Verify escrow was created
        self.assertIsNotNone(db_fundraise.escrow)
        self.assertEqual(db_fundraise.escrow.created_by, self.user)
        self.assertEqual(db_fundraise.escrow.hold_type, "FUNDRAISE")
        self.assertEqual(db_fundraise.escrow.content_type.model, "fundraise")
        self.assertEqual(db_fundraise.escrow.object_id, db_fundraise.id)

    def test_create_fundraise_invalid_document_type(self):
        # Arrange
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="NOT_PREREGISTRATION"
        )
        data = {
            "goal_amount": "100.00",
            "goal_currency": USD,
            "unified_document_id": unified_document.id,
            "recipient_user_id": self.user.id,
        }

        # Act
        serializer = FundraiseCreateSerializer(data=data)
        is_valid = serializer.is_valid()

        # Assert
        self.assertFalse(is_valid)
        self.assertEqual(
            str(serializer.errors["non_field_errors"][0]),
            "Fundraise must be for a preregistration",
        )

    def test_create_fundraise_invalid_goal_amount(self):
        # Arrange
        data = {
            "goal_amount": "100.00abc",
            "goal_currency": USD,
            "unified_document_id": 1,
            "recipient_user_id": self.user.id,
        }

        # Act
        serializer = FundraiseCreateSerializer(data=data)
        is_valid = serializer.is_valid()

        # Assert
        self.assertFalse(is_valid)
        self.assertEqual(
            str(serializer.errors["goal_amount"][0]), "A valid number is required."
        )

    def test_create_fundraise_negative_goal_amount(self):
        # Arrange
        data = {
            "goal_amount": "-100.00",
            "goal_currency": USD,
            "unified_document_id": 1,
            "recipient_user_id": self.user.id,
        }

        # Act
        serializer = FundraiseCreateSerializer(data=data)
        is_valid = serializer.is_valid()

        # Assert
        self.assertFalse(is_valid)
        self.assertEqual(
            str(serializer.errors["non_field_errors"][0]),
            "goal_amount must be greater than 0",
        )

    def test_create_fundraise_invalid_currency(self):
        # Arrange
        data = {
            "goal_amount": "100.00",
            "goal_currency": "RSC",
            "unified_document_id": 1,
            "recipient_user_id": self.user.id,
        }

        # Act
        serializer = FundraiseCreateSerializer(data=data)
        is_valid = serializer.is_valid()

        # Assert
        self.assertFalse(is_valid)
        self.assertEqual(
            str(serializer.errors["non_field_errors"][0]), "goal_currency must be USD"
        )

    def test_create_fundraise_already_exists(self):
        # Arrange
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        goal_amount = Decimal("100.00")

        # Create initial fundraise using the service
        self.service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=unified_document,
            goal_amount=goal_amount,
            goal_currency=USD,
            status=Fundraise.OPEN,
        )

        data = {
            "goal_amount": str(goal_amount),
            "goal_currency": USD,
            "unified_document_id": unified_document.id,
            "recipient_user_id": self.user.id,
        }

        # Act
        serializer = FundraiseCreateSerializer(data=data)
        is_valid = serializer.is_valid()

        # Assert
        self.assertFalse(is_valid)
        self.assertEqual(
            str(serializer.errors["non_field_errors"][0]), "Fundraise already exists"
        )
