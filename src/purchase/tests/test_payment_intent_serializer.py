from decimal import Decimal

from django.test import TestCase

from purchase.serializers.payment_intent_serializer import PaymentIntentSerializer


class PaymentIntentSerializerTest(TestCase):
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

    def test_valid_float_data(self):
        # Arrange
        data = {
            "amount": 100.5,  # 100.5 RSC
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["amount"], Decimal("100.50"))

    def test_valid_minimum_amount(self):
        # Arrange
        data = {
            "amount": 0.01,  # Minimum allowed amount
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["amount"], Decimal("0.01"))

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

    def test_amount_below_minimum_edge_case(self):
        # Arrange
        data = {
            "amount": 0.001,  # Below minimum (less than 0.01)
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
