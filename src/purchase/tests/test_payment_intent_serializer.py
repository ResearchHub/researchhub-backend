from django.test import TestCase

from purchase.related_models.constants.currency import RSC, USD
from purchase.serializers.payment_intent_serializer import PaymentIntentSerializer


class PaymentIntentSerializerTest(TestCase):
    def test_valid_usd_data(self):
        # Arrange
        data = {
            "amount": 1000,  # $10.00
            "currency": USD,
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["amount"], 1000)
        self.assertEqual(serializer.validated_data["currency"], USD)

    def test_valid_rsc_data(self):
        # Arrange
        data = {
            "amount": 100,  # 100 RSC
            "currency": RSC,
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["amount"], 100)
        self.assertEqual(serializer.validated_data["currency"], RSC)

    def test_default_currency(self):
        # Arrange
        data = {
            "amount": 1000,
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["currency"], USD)

    def test_amount_below_minimum(self):
        # Arrange
        data = {
            "amount": 0,  # Below minimum $0.01
            "currency": USD,
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertFalse(serializer.is_valid())
        self.assertIn("amount", serializer.errors)

    def test_invalid_currency(self):
        # Arrange
        data = {
            "amount": 1000,
            "currency": "invalid",
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertFalse(serializer.is_valid())
        self.assertIn("currency", serializer.errors)

    def test_missing_amount(self):
        # Arrange
        data = {
            "currency": USD,
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertFalse(serializer.is_valid())
        self.assertIn("amount", serializer.errors)
