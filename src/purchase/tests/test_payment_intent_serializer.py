from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from purchase.related_models.fundraise_model import Fundraise
from purchase.serializers.payment_intent_serializer import PaymentIntentSerializer
from reputation.models import Escrow
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_user


class PaymentIntentSerializerTest(TestCase):
    def setUp(self):
        self.user = create_user()
        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION",
        )
        self.fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=self.unified_document,
            goal_amount=1000,
            status=Fundraise.OPEN,
        )
        self.escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.FUNDRAISE,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
        )
        self.fundraise.escrow = self.escrow
        self.fundraise.save()

    def test_valid_data(self):
        # Arrange
        data = {
            "amount": 100,  # 100 RSC
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["amount"], Decimal("100"))

    def test_amount_below_minimum(self):
        # Arrange
        data = {
            "amount": 0,  # Below minimum
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertFalse(serializer.is_valid())
        self.assertIn("amount", serializer.errors)

    def test_missing_amount(self):
        # Arrange
        data = {}

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertFalse(serializer.is_valid())
        self.assertIn("amount", serializer.errors)

    def test_valid_decimal_amount(self):
        # Arrange
        data = {
            "amount": "50.5",  # 50.5 RSC (fractional)
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["amount"], Decimal("50.5"))

    def test_valid_data_with_fundraise_id(self):
        # Arrange
        data = {
            "amount": 100,
            "fundraise_id": self.fundraise.id,
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["amount"], Decimal("100"))
        self.assertEqual(serializer.validated_data["fundraise_id"], self.fundraise.id)

    def test_fundraise_id_null_is_valid(self):
        # Arrange
        data = {
            "amount": 100,
            "fundraise_id": None,
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertTrue(serializer.is_valid())
        self.assertIsNone(serializer.validated_data.get("fundraise_id"))

    def test_fundraise_id_not_found(self):
        # Arrange
        data = {
            "amount": 100,
            "fundraise_id": 99999,  # Non-existent ID
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertFalse(serializer.is_valid())
        self.assertIn("fundraise_id", serializer.errors)
        self.assertIn("not found", str(serializer.errors["fundraise_id"]))

    def test_fundraise_id_closed_fundraise(self):
        # Arrange
        self.fundraise.status = Fundraise.CLOSED
        self.fundraise.save()

        data = {
            "amount": 100,
            "fundraise_id": self.fundraise.id,
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertFalse(serializer.is_valid())
        self.assertIn("fundraise_id", serializer.errors)
        self.assertIn("not open", str(serializer.errors["fundraise_id"]))

    def test_fundraise_id_expired_fundraise(self):
        # Arrange
        from datetime import datetime, timedelta

        import pytz

        self.fundraise.end_date = datetime.now(pytz.UTC) - timedelta(days=1)
        self.fundraise.save()

        data = {
            "amount": 100,
            "fundraise_id": self.fundraise.id,
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertFalse(serializer.is_valid())
        self.assertIn("fundraise_id", serializer.errors)
        self.assertIn("expired", str(serializer.errors["fundraise_id"]))
