from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers
from rest_framework.test import APITestCase

from purchase.models import Fundraise
from purchase.related_models.constants.currency import USD
from purchase.serializers.fundraise_create_serializer import FundraiseCreateSerializer
from purchase.services.fundraise_service import FundraiseService
from reputation.models import Escrow
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

        # Create initial fundraise
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=unified_document,
            goal_amount=Decimal("100.00"),
            goal_currency=USD,
            status=Fundraise.OPEN,
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
            str(serializer.errors["non_field_errors"][0]), "Fundraise already exists"
        )
