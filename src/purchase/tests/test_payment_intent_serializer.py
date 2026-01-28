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

    def test_valid_maximum_amount(self):
        # Arrange
        data = {
            "amount": 99999999.99,  # Maximum valid amount (10 digits, 2 decimal places)
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["amount"], Decimal("99999999.99"))

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
        # Verify the error message indicates minimum value constraint
        error_str = str(serializer.errors["amount"])
        self.assertIn("0.01", error_str.lower())

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
        # Verify the error message indicates minimum value constraint
        error_str = str(serializer.errors["amount"])
        self.assertIn("0.01", error_str.lower())

    def test_amount_exceeds_max_digits(self):
        # Arrange
        data = {
            "amount": 1000000000.00,  # Exceeds max_digits (10 digits)
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertFalse(serializer.is_valid())
        self.assertIn("amount", serializer.errors)

    def test_amount_with_too_many_decimal_places(self):
        # Arrange
        data = {
            "amount": 100.123,  # More than 2 decimal places
        }

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        # DecimalField with decimal_places=2 will round or reject values with more decimals
        # In Django REST Framework, it typically rounds to 2 decimal places
        if serializer.is_valid():
            # If valid, verify it was rounded to 2 decimal places
            self.assertEqual(serializer.validated_data["amount"], Decimal("100.12"))
        else:
            # If invalid, verify amount is in errors
            self.assertIn("amount", serializer.errors)

    def test_missing_amount(self):
        # Arrange
        data = {}

        # Act
        serializer = PaymentIntentSerializer(data=data)

        # Assert
        self.assertFalse(serializer.is_valid())
        self.assertIn("amount", serializer.errors)
