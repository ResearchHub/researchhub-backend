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
        self.assertEqual(serializer.validated_data["amount"], 100)

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

    def test_valid_float_amount(self):
        # Arrange
        data = {
            "amount": 50.5,  # 50.5 RSC (fractional)
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["amount"], 50.5)
